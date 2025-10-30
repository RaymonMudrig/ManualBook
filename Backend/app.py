from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    BASE_DIR_TEMP = Path(__file__).resolve().parent.parent
    env_path = BASE_DIR_TEMP / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ Loaded environment from {env_path}")
except ImportError:
    print("⚠ python-dotenv not installed, skipping .env file loading")
    pass

# Add parent directory to path for llm module import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from llm import get_embeddings, generate_answer, LLMServiceError
from catalog import CatalogBuilder
from retrieval import QueryClassifier, CatalogRetriever

try:
    import chromadb
    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'chromadb'. Install it with 'pip install chromadb' and retry."
    ) from exc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
OUTPUT_DIR = BASE_DIR / "output"
INDEX_DIR = OUTPUT_DIR / "vector_index"
CATALOG_DIR = OUTPUT_DIR / "catalog"
DEFAULT_PORT = 8800

# Configuration
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")
VECTOR_COLLECTION = os.environ.get("VECTOR_COLLECTION", "manual_chunks")
DEFAULT_TOP_K = int(os.environ.get("DEFAULT_TOP_K", "5"))
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.7"))
RETRY_PAUSE = 2.0


class QueryPayload(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=1000, description="Natural language query."
    )
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=20)
    threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Optional similarity threshold override (0-1)."
    )

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Query cannot be empty.")
        # Limit query length for safety
        if len(cleaned) > 1000:
            raise ValueError("Query is too long (max 1000 characters).")
        # Remove excessive whitespace
        cleaned = " ".join(cleaned.split())
        return cleaned


@dataclass
class RetrievalResult:
    id: str
    text: str
    metadata: Dict[str, str]
    score: float


app = FastAPI(title="Semantic Query Agent", version="1.0.0")

# CORS configuration - use environment variable for allowed origins
# For production, set CORS_ORIGINS="https://yourdomain.com,https://app.yourdomain.com"
# For development, use "*" or leave empty to allow all
cors_origins_str = os.environ.get("CORS_ORIGINS", "*")
if cors_origins_str == "*":
    allowed_origins = ["*"]
    logger.warning("CORS is set to allow all origins. This is not recommended for production!")
else:
    allowed_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]
    logger.info(f"CORS allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Mount images directory to serve embedded images from chunks
IMAGE_DIR = OUTPUT_DIR / "images"
if IMAGE_DIR.exists():
    app.mount("/images", StaticFiles(directory=IMAGE_DIR), name="images")

# Mount articles directory to serve catalog articles with images
ARTICLES_DIR = OUTPUT_DIR / "catalog" / "articles"
if ARTICLES_DIR.exists():
    app.mount("/articles", StaticFiles(directory=ARTICLES_DIR), name="articles")

# Mount md directory to serve markdown documents and their images
MD_DIR = BASE_DIR / "md"
if MD_DIR.exists():
    app.mount("/md", StaticFiles(directory=MD_DIR), name="md")

client: ClientAPI = chromadb.PersistentClient(path=str(INDEX_DIR))
try:
    collection: Collection = client.get_or_create_collection(name=VECTOR_COLLECTION)
except Exception as exc:  # pragma: no cover - defensive
    raise SystemExit(f"Unable to initialize vector collection '{VECTOR_COLLECTION}': {exc}")

# Initialize catalog system (Phase 2)
catalog_builder = None
query_classifier = None
catalog_retriever = None

if CATALOG_DIR.exists() and (CATALOG_DIR / "catalog.json").exists():
    try:
        catalog_builder = CatalogBuilder(CATALOG_DIR)
        query_classifier = QueryClassifier()
        catalog_retriever = CatalogRetriever(
            collection,
            catalog_builder,
            default_top_k=DEFAULT_TOP_K,
            include_related=True
        )
        logger.info("✓ Catalog system initialized (Phase 2 mode)")
    except Exception as exc:
        logger.warning(f"⚠ Failed to initialize catalog system: {exc}")
        logger.warning("  Falling back to chunk-based retrieval (Phase 1 mode)")
else:
    logger.warning(f"⚠ Catalog not found at {CATALOG_DIR}")
    logger.warning("  Using chunk-based retrieval (Phase 1 mode)")
    logger.warning("  Run 'python Ingress/build_catalog.py' to enable Phase 2 features")


# Embedding function now uses centralized llm service
def embed_text(text: str) -> List[float]:
    """Embed a single text using the centralized LLM service."""
    try:
        return get_embeddings([text])[0]
    except LLMServiceError as exc:
        logger.error(f"Failed to embed text: {exc}")
        raise RuntimeError(f"Failed to fetch embedding: {exc}") from exc


def query_vector_store(
    query: str,
    top_k: int,
    threshold: float,
) -> Tuple[List[RetrievalResult], float]:
    embedding = embed_text(query)
    result = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        include=["distances", "documents", "metadatas"],
    )
    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    ids = result.get("ids") or [[]]
    distances = result.get("distances") or [[]]

    retrieved: List[RetrievalResult] = []
    best_score = 0.0
    for doc, meta, distance, chunk_id in zip(
        documents[0], metadatas[0], distances[0], ids[0]
    ):
        similarity = 1 - float(distance)
        best_score = max(best_score, similarity)
        metadata = {str(k): str(v) for k, v in (meta or {}).items()}
        retrieved.append(
            RetrievalResult(
                id=str(chunk_id),
                text=str(doc),
                metadata=metadata,
                score=similarity,
            )
        )
    filtered = [item for item in retrieved if item.score >= threshold]
    return filtered, best_score


def boost_scores_by_synonyms_and_codes(
    query: str,
    results: List[RetrievalResult],
    catalog_data: Dict,
    boost_factor: float = 0.15
) -> List[RetrievalResult]:
    """Boost scores for results matching query synonyms or codes.

    Args:
        query: User query string
        results: List of retrieval results
        catalog_data: Catalog JSON data with article metadata
        boost_factor: How much to boost matching scores (default: 0.15)

    Returns:
        Updated list of results with boosted scores
    """
    if not catalog_data or "articles" not in catalog_data:
        return results

    query_lower = query.lower()
    query_upper = query.upper()
    articles = catalog_data.get("articles", {})

    for result in results:
        article_id = result.metadata.get("article_id")
        if not article_id or article_id not in articles:
            continue

        article_meta = articles[article_id]
        synonyms = article_meta.get("synonyms", [])
        codes = article_meta.get("codes", [])

        # Check synonym matches (case-insensitive)
        synonym_match = any(
            syn.lower() in query_lower
            for syn in synonyms
        )

        # Check code matches (case-insensitive, exact or partial)
        code_match = any(
            code.upper() in query_upper
            for code in codes
        )

        # Boost score if match found
        if synonym_match or code_match:
            old_score = result.score
            result.score = min(1.0, result.score + boost_factor)
            logger.debug(
                f"Boosted {article_id}: {old_score:.3f} → {result.score:.3f} "
                f"(synonym={synonym_match}, code={code_match})"
            )

    # Re-sort by score (descending)
    results.sort(key=lambda x: x.score, reverse=True)
    return results


def summarize_with_llm(query: str, context: str, sources: List[Dict[str, str]]) -> str:
    """Generate an answer using the centralized LLM service."""
    try:
        return generate_answer(query, context, sources)
    except LLMServiceError as exc:
        logger.error(f"Failed to generate answer: {exc}")
        raise RuntimeError(f"LLM completion error: {exc}") from exc


def perform_web_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    if SERPER_API_KEY:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": num_results}
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Serper search error {response.status_code}: {response.text}"
            )
        data = response.json()
        hits = data.get("organic") or []
        results = []
        for hit in hits[:num_results]:
            results.append(
                {
                    "title": hit.get("title") or "Untitled result",
                    "url": hit.get("link") or "",
                    "snippet": hit.get("snippet") or "",
                }
            )
        return results

    # Fallback to DuckDuckGo Instant Answer API (no key required)
    response = requests.get(
        "https://api.duckduckgo.com/",
        params={
            "q": query,
            "format": "json",
            "no_html": 1,
            "no_redirect": 1,
        },
        timeout=15,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"DuckDuckGo search error {response.status_code}: {response.text}"
        )
    data = response.json()
    results: List[Dict[str, str]] = []

    def add_result(item: Dict[str, str]) -> None:
        if item.get("FirstURL") and item.get("Text"):
            results.append(
                {
                    "title": item.get("Text").split(" - ")[0],
                    "url": item.get("FirstURL"),
                    "snippet": item.get("Text"),
                }
            )

    related = data.get("RelatedTopics", [])
    for entry in related:
        if "FirstURL" in entry:
            add_result(entry)
        elif "Topics" in entry:
            for sub in entry["Topics"]:
                add_result(sub)
        if len(results) >= num_results:
            break
    return results[:num_results]


def synthesize_web_answer(query: str, results: List[Dict[str, str]]) -> str:
    if not results:
        return (
            "I could not find relevant information on the web. "
            "Please refine your query or try again later."
        )
    summaries = []
    for item in results:
        title = item.get("title") or "Untitled"
        snippet = item.get("snippet") or ""
        url = item.get("url") or ""
        summaries.append(f"{title}\nURL: {url}\nSnippet: {snippet}")
    context = "\n\n".join(summaries)
    return summarize_with_llm(query, context, results)


def build_context_block(results: List[RetrievalResult]) -> Tuple[str, List[Dict[str, str]]]:
    context_lines = []
    sources: List[Dict[str, str]] = []
    for item in results:
        title = item.metadata.get("title") or item.metadata.get("source_title") or ""
        src_kind = item.metadata.get("source_kind", "")
        src_file = item.metadata.get("source_file", "")

        # Extract semantic chunking metadata
        heading_hierarchy = item.metadata.get("heading_hierarchy", "")
        heading_level = item.metadata.get("heading_level")
        section_title = item.metadata.get("section_title", "")
        parent_title = item.metadata.get("parent_title", "")
        token_count = item.metadata.get("token_count")

        # Build enhanced source info
        source_info = {
            "id": item.id,
            "title": title or "Untitled section",
            "score": item.score,
            "source_kind": src_kind,
            "source_file": src_file,
        }

        # Add hierarchy information if available
        if heading_hierarchy:
            source_info["heading_path"] = heading_hierarchy
        if heading_level:
            source_info["level"] = int(heading_level) if isinstance(heading_level, str) else heading_level
        if section_title:
            source_info["section"] = section_title
        if parent_title:
            source_info["parent"] = parent_title
        if token_count:
            source_info["tokens"] = int(token_count) if isinstance(token_count, str) else token_count

        sources.append(source_info)

        # Build context with hierarchy path
        context_parts = []
        if heading_hierarchy:
            context_parts.append(f"📍 Path: {heading_hierarchy}")
        else:
            context_parts.append(f"Title: {title or 'Untitled'}")

        context_parts.append(f"Score: {item.score:.3f}")
        context_parts.append(f"Source: {src_kind} {src_file}")

        if parent_title:
            context_parts.append(f"Parent Section: {parent_title}")

        context_parts.append(f"Content:\n{item.text}")

        context_lines.append("\n".join(context_parts))

    return "\n\n---\n\n".join(context_lines), sources


def build_catalog_context(article_results: List[Dict], max_context_chars: int = 1000) -> Tuple[str, List[Dict[str, object]]]:
    """Build context from catalog article results (Phase 2).

    Args:
        article_results: List of article results from CatalogRetriever
        max_context_chars: Maximum characters per article for LLM context (default: 1000)

    Returns:
        Tuple of (context_block for LLM, sources with complete content)
    """
    context_lines = []
    sources: List[Dict[str, object]] = []

    for result in article_results:
        article = result["article"]
        score = result["score"]
        related = result.get("related", {})

        # Build source info with COMPLETE content (for user)
        source_info = {
            "article_id": article["id"],
            "title": article["title"],
            "score": score,
            "intent": article["intent"],
            "category": article["category"],
            "content": article["content"],  # FULL content for user
        }

        # Add images if present
        if article.get("images"):
            source_info["images"] = article["images"]

        # Add related articles
        if related.get("parent"):
            source_info["parent"] = {
                "id": related["parent"]["id"],
                "title": related["parent"]["title"]
            }

        if related.get("children"):
            source_info["children"] = [
                {"id": c["id"], "title": c["title"]}
                for c in related["children"]
            ]

        if related.get("see_also"):
            source_info["see_also"] = [
                {"id": s["id"], "title": s["title"]}
                for s in related["see_also"]
            ]

        sources.append(source_info)

        # Build context block
        context_parts = []
        context_parts.append(f"Article: {article['title']}")
        context_parts.append(f"ID: {article['id']}")
        context_parts.append(f"Score: {score:.3f}")
        context_parts.append(f"Intent: {article['intent']}")
        context_parts.append(f"Category: {article['category']}")

        # Add relationships
        if related.get("parent"):
            context_parts.append(f"Parent: {related['parent']['title']}")

        if related.get("children"):
            child_titles = [c["title"] for c in related["children"][:3]]
            context_parts.append(f"Children: {', '.join(child_titles)}")

        if related.get("see_also"):
            see_also_titles = [s["title"] for s in related["see_also"][:3]]
            context_parts.append(f"See also: {', '.join(see_also_titles)}")

        # Add TRUNCATED content for LLM context (to avoid token limit)
        content_for_llm = article['content']
        if len(content_for_llm) > max_context_chars:
            content_for_llm = content_for_llm[:max_context_chars] + "... [truncated for context]"

        context_parts.append(f"\nContent:\n{content_for_llm}")

        context_lines.append("\n".join(context_parts))

    return "\n\n---\n\n".join(context_lines), sources


@app.get("/")
def read_root() -> FileResponse:
    """Main page - unified document viewer and query interface."""
    viewer_file = STATIC_DIR / "viewer.html"
    if not viewer_file.exists():
        raise HTTPException(status_code=404, detail="Viewer page not found.")
    return FileResponse(viewer_file)


@app.get("/viewer")
def read_viewer() -> FileResponse:
    """Redirect to main page."""
    viewer_file = STATIC_DIR / "viewer.html"
    if not viewer_file.exists():
        raise HTTPException(status_code=404, detail="Viewer page not found.")
    return FileResponse(viewer_file)


@app.get("/query")
def read_query() -> FileResponse:
    """Legacy query page - redirect to main page."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(index_file)


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/documents")
def list_documents() -> JSONResponse:
    """List all available markdown documents in the md/ directory."""
    if not MD_DIR.exists():
        raise HTTPException(status_code=404, detail="MD directory not found.")

    documents = []
    for md_file in MD_DIR.glob("*.md"):
        # Skip .mdx files (original language)
        if md_file.suffix == ".mdx":
            continue

        # Check for associated images directory
        images_dir = MD_DIR / f"{md_file.stem}_images"
        has_images = images_dir.exists() and images_dir.is_dir()

        documents.append({
            "id": md_file.stem,
            "name": md_file.name,
            "title": md_file.stem.replace("_", " "),
            "has_images": has_images,
        })

    return JSONResponse({"documents": documents})


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str) -> JSONResponse:
    """Get a specific document's content and generate TOC."""
    if not MD_DIR.exists():
        raise HTTPException(status_code=404, detail="MD directory not found.")

    # Sanitize doc_id to prevent path traversal
    doc_id = doc_id.replace("..", "").replace("/", "").replace("\\", "")

    md_file = MD_DIR / f"{doc_id}.md"
    if not md_file.exists():
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")

    try:
        content = md_file.read_text(encoding="utf-8")

        # Parse TOC from headings
        toc = parse_markdown_toc(content)

        # Clean up content: remove METADATA comments
        content = clean_markdown_content(content)

        # Fix image paths to use /md/ prefix
        content = fix_image_paths(content, doc_id)

        return JSONResponse({
            "id": doc_id,
            "name": md_file.name,
            "content": content,
            "toc": toc,
        })
    except Exception as exc:
        logger.error(f"Error reading document {doc_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def parse_markdown_toc(content: str) -> List[Dict[str, object]]:
    """Parse markdown content and extract heading hierarchy for TOC.

    Returns a flat list of headings with level and id information.
    """
    import re

    toc = []
    lines = content.split("\n")
    heading_counts: Dict[str, int] = {}

    for line in lines:
        # Match markdown headings (# to ######)
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()

            # Remove emoji and special characters for ID
            clean_title = re.sub(r"[^\w\s-]", "", title)
            heading_id = clean_title.lower().replace(" ", "-")

            # Handle duplicate IDs
            if heading_id in heading_counts:
                heading_counts[heading_id] += 1
                heading_id = f"{heading_id}-{heading_counts[heading_id]}"
            else:
                heading_counts[heading_id] = 0

            toc.append({
                "level": level,
                "title": title,
                "id": heading_id,
            })

    return toc


def clean_markdown_content(content: str) -> str:
    """Remove METADATA HTML comments from markdown content."""
    import re

    # Remove HTML comments that contain METADATA
    content = re.sub(r"<!--METADATA.*?-->", "", content, flags=re.DOTALL)

    # Remove any other HTML comments (optional)
    # content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)

    return content


def fix_image_paths(content: str, doc_id: str) -> str:
    """Fix image paths in markdown to use /md/ prefix."""
    import re

    # Replace image paths like ![alt](image.png) with ![alt](/md/DocName_images/image.png)
    def replace_image(match):
        alt = match.group(1)
        path = match.group(2)

        # Skip if already absolute or HTTP URL
        if path.startswith("http") or path.startswith("/"):
            return match.group(0)

        # If path already contains the images directory, just add /md/ prefix
        if path.startswith(f"{doc_id}_images/"):
            return f"![{alt}](/md/{path})"

        # Otherwise, assume images are in {doc_id}_images/ directory
        return f"![{alt}](/md/{doc_id}_images/{path})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_image, content)


@app.post("/api/classify")
def handle_classify(payload: QueryPayload) -> JSONResponse:
    """Classify a query by intent and category (Phase 2 feature)."""
    if not query_classifier:
        raise HTTPException(
            status_code=503,
            detail="Query classifier not available. Catalog system not initialized."
        )

    try:
        classification = query_classifier.classify(payload.query)
        return JSONResponse({
            "query": payload.query,
            "classification": classification
        })
    except Exception as exc:
        logger.error(f"Classification failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/query")
def handle_query(payload: QueryPayload) -> JSONResponse:
    logger.info(f"Received query: '{payload.query[:100]}...' (top_k={payload.top_k})")
    threshold = (
        payload.threshold
        if payload.threshold is not None
        else max(0.0, min(1.0, SIMILARITY_THRESHOLD))
    )
    logger.debug(f"Using similarity threshold: {threshold}")
    steps: List[Dict[str, object]] = []

    # Phase 2: Use catalog retriever if available
    if catalog_retriever and query_classifier:
        try:
            # Step 1: Classify query
            classification = query_classifier.classify(payload.query)
            logger.info(f"Classification: intent={classification['intent']}, "
                       f"category={classification['category']}, "
                       f"confidence={classification['confidence']:.2f}")
            steps.append({
                "stage": "classification",
                "status": "success",
                "detail": f"Classified as {classification['intent']}/{classification['category']}",
                "intent": classification["intent"],
                "category": classification["category"],
                "confidence": classification["confidence"]
            })

            # Step 2: Retrieve articles with metadata filtering
            article_results = catalog_retriever.retrieve(
                payload.query,
                classification=classification,
                top_k=payload.top_k
            )
            logger.info(f"Catalog retrieval: {len(article_results)} articles")
            steps.append({
                "stage": "catalog_retrieval",
                "status": "success",
                "detail": f"Retrieved {len(article_results)} complete articles",
                "count": len(article_results)
            })

            # Step 3: Build context and sources from articles
            if article_results:
                context_block, sources = build_catalog_context(article_results)
                best_score = max([r["score"] for r in article_results]) if article_results else 0.0

                steps.append({
                    "stage": "vector_search",
                    "top_score": round(best_score, 4),
                    "kept": len(article_results),
                    "threshold": threshold,
                    "status": "success",
                    "detail": "Retrieved complete articles with relationships"
                })

                # Step 4: Generate answer
                try:
                    answer = summarize_with_llm(payload.query, context_block, sources)
                    steps.append({
                        "stage": "rag_generation",
                        "status": "success",
                        "detail": "Generated answer using catalog articles"
                    })

                    return JSONResponse({
                        "query": payload.query,
                        "answer": answer,
                        "mode": "catalog_rag",
                        "sources": sources,
                        "classification": classification,
                        "steps": steps
                    })
                except Exception as exc:
                    logger.error(f"Answer generation failed: {exc}")
                    steps.append({
                        "stage": "rag_generation",
                        "status": "failed",
                        "detail": str(exc)
                    })

        except Exception as exc:
            logger.warning(f"Catalog retrieval failed: {exc}, falling back to Phase 1")
            steps.append({
                "stage": "catalog_retrieval",
                "status": "failed",
                "detail": f"Falling back to chunk-based retrieval: {exc}"
            })

    # Phase 1: Chunk-based retrieval (fallback or when catalog not available)
    try:
        retrieved, best_score = query_vector_store(
            payload.query, payload.top_k, threshold
        )
        logger.info(f"Vector search: retrieved {len(retrieved)} chunks, best_score={best_score:.4f}")

        # Boost scores based on synonym and code matches
        if catalog_builder and retrieved:
            try:
                catalog_data = catalog_builder.catalog
                retrieved = boost_scores_by_synonyms_and_codes(
                    payload.query, retrieved, catalog_data
                )
                # Recalculate best_score after boosting
                if retrieved:
                    best_score = max(r.score for r in retrieved)
                logger.info(f"After synonym/code boost: best_score={best_score:.4f}")
            except Exception as boost_exc:
                logger.warning(f"Synonym/code boosting failed: {boost_exc}")

        steps.append(
            {
                "stage": "vector_search",
                "top_score": round(best_score, 4),
                "kept": len(retrieved),
                "threshold": threshold,
                "status": "success",
                "detail": (
                    "Retrieved candidate chunks from vector index and filtered by similarity."
                ),
            }
        )
    except Exception as exc:
        logger.error(f"Vector search failed: {exc}")
        steps.append(
            {
                "stage": "vector_search",
                "status": "failed",
                "detail": str(exc),
            }
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response_payload: Dict[str, object] = {
        "query": payload.query,
        "answer": "",
        "mode": "",
        "sources": [],
        "steps": steps,
    }

    use_fallback = not retrieved
    if retrieved:
        context_block, sources = build_context_block(retrieved)
        try:
            answer = summarize_with_llm(payload.query, context_block, sources)
            response_payload.update(
                {
                    "answer": answer,
                    "mode": "rag",
                    "sources": sources,
                }
            )
        except Exception as exc:
            steps.append(
                {
                    "stage": "rag_generation",
                    "status": "failed",
                    "detail": str(exc),
                }
            )
            use_fallback = True
        else:
            steps.append(
                {
                    "stage": "rag_generation",
                    "status": "success",
                    "detail": "Generated answer using retrieved context.",
                }
            )
            if best_score < threshold:
                use_fallback = True
    if use_fallback:
        logger.info("Using web search fallback")
        try:
            results = perform_web_search(payload.query)
            logger.info(f"Web search returned {len(results)} results")
            steps.append(
                {
                    "stage": "web_search",
                    "status": "success",
                    "detail": f"Retrieved {len(results)} web results.",
                }
            )
            web_answer = synthesize_web_answer(payload.query, results)
            response_payload.update(
                {
                    "fallback_results": results,
                    "mode": "web" if not response_payload["answer"] else "hybrid",
                    "answer": (
                        response_payload["answer"] + "\n\n"
                        if response_payload["answer"]
                        else ""
                    )
                    + web_answer,
                }
            )
        except Exception as exc:
            steps.append(
                {
                    "stage": "web_search",
                    "status": "failed",
                    "detail": str(exc),
                }
            )
            if not response_payload["answer"]:
                response_payload["answer"] = (
                    "The system could not retrieve sufficient information from the knowledge "
                    "base or the web. Please try a different query."
                )
                response_payload["mode"] = "none"
    return JSONResponse(response_payload)


def run_server(host: str = "0.0.0.0", port: int = DEFAULT_PORT, reload: bool = False) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime guard
        raise SystemExit(
            "Missing dependency 'uvicorn'. Install it with 'pip install uvicorn[standard]' and retry."
        ) from exc

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    run_server(port=DEFAULT_PORT, reload=False)
