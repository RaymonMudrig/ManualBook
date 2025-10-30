#!/usr/bin/env python3
"""
Catalog retriever for hybrid semantic search with metadata filtering.

Combines:
1. Query classification (intent/category filtering)
2. Semantic search in ChromaDB
3. Complete article retrieval from catalog
4. Related article expansion (parent, children, see-also)

Usage:
    from retrieval.catalog_retriever import CatalogRetriever

    retriever = CatalogRetriever(chroma_collection, catalog_builder)
    results = retriever.retrieve(
        query="How do I set up workspace?",
        classification={"intent": "do", "category": "application"},
        top_k=3
    )
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import CatalogBuilder
from llm import get_embeddings

try:
    from chromadb.api.models.Collection import Collection
except ModuleNotFoundError:
    # ChromaDB not installed - define placeholder
    Collection = None


class CatalogRetriever:
    """Retrieve complete articles with metadata filtering and relationship expansion."""

    def __init__(
        self,
        chroma_collection,
        catalog_builder: CatalogBuilder,
        default_top_k: int = 3,
        include_related: bool = True
    ):
        """Initialize retriever.

        Args:
            chroma_collection: ChromaDB collection with vectorized articles
            catalog_builder: CatalogBuilder instance for article lookup
            default_top_k: Default number of articles to retrieve
            include_related: Whether to automatically include related articles
        """
        self.chroma = chroma_collection
        self.catalog = catalog_builder
        self.default_top_k = default_top_k
        self.include_related = include_related

    def retrieve(
        self,
        query: str,
        classification: Optional[Dict] = None,
        top_k: Optional[int] = None,
        include_related: Optional[bool] = None,
        use_intent_fallback: bool = True
    ) -> List[Dict]:
        """Retrieve articles for a query.

        Args:
            query: User query string
            classification: Query classification (intent, category, topics)
            top_k: Number of articles to retrieve (default: self.default_top_k)
            include_related: Whether to include related articles (default: self.include_related)
            use_intent_fallback: Try alternative intent if results are poor (default: True)

        Returns:
            List of article results with content and metadata:
            [
                {
                    "article": {...},  # Complete article from catalog
                    "score": 0.85,     # Similarity score
                    "related": {       # Related articles
                        "parent": {...} or None,
                        "children": [...],
                        "see_also": [...]
                    }
                },
                ...
            ]
        """
        if top_k is None:
            top_k = self.default_top_k

        if include_related is None:
            include_related = self.include_related

        # Step 1: Try primary retrieval
        results = self._retrieve_with_classification(
            query, classification, top_k, include_related
        )

        # Step 2: Intent fallback if results are poor
        if use_intent_fallback and classification:
            should_fallback = (
                len(results) == 0 or  # No results
                (results and max([r["score"] for r in results]) < 0.70)  # Low scores
            )

            if should_fallback:
                # Try alternative intent
                alt_results = self._retrieve_with_alternative_intent(
                    query, classification, top_k, include_related
                )

                # Merge and re-rank results
                results = self._merge_results(results, alt_results, top_k)

        return results

    def _retrieve_with_classification(
        self,
        query: str,
        classification: Optional[Dict],
        top_k: int,
        include_related: bool
    ) -> List[Dict]:
        """Retrieve articles with given classification."""
        # Expand query with catalog synonyms
        expanded_query = self._expand_query_with_catalog(query)

        # Build metadata filter from classification
        where_filter = self._build_filter(classification)

        # Semantic search with metadata filtering (using expanded query)
        search_results = self._semantic_search(expanded_query, where_filter, top_k)

        # Get unique article IDs (deduplicate chunks)
        article_ids_with_scores = self._deduplicate_articles(search_results)

        # Retrieve complete articles from catalog
        results = []
        for article_id, score in article_ids_with_scores[:top_k]:
            try:
                # Load article
                article = self.catalog.get_article(article_id)

                # Build result
                result = {
                    "article": article,
                    "score": score,
                    "related": {}
                }

                # Add related articles if requested
                if include_related:
                    result["related"] = self._get_related_articles(article_id)

                results.append(result)

            except Exception as e:
                print(f"⚠ Failed to retrieve article '{article_id}': {e}")
                continue

        # Boost scores for exact title/ID matches
        results = self._boost_exact_matches(query, results)

        # Check relevance of top results
        results = self._check_relevance(query, results)

        return results

    def _retrieve_with_alternative_intent(
        self,
        query: str,
        classification: Dict,
        top_k: int,
        include_related: bool
    ) -> List[Dict]:
        """Retry retrieval with alternative intent (do ↔ learn)."""
        # Get alternative intent
        original_intent = classification.get("intent")
        if original_intent == "do":
            alt_intent = "learn"
        elif original_intent == "learn":
            alt_intent = "do"
        else:
            # No clear alternative for "trouble"
            return []

        # Create alternative classification
        alt_classification = {**classification, "intent": alt_intent}

        print(f"🔄 Intent fallback: {original_intent} → {alt_intent}")

        # Retrieve with alternative intent
        return self._retrieve_with_classification(
            query, alt_classification, top_k, include_related
        )

    def _merge_results(
        self,
        primary_results: List[Dict],
        fallback_results: List[Dict],
        top_k: int
    ) -> List[Dict]:
        """Merge primary and fallback results, de-duplicate and re-rank."""
        # Collect all results with their scores
        all_results = {}

        # Add primary results (full weight)
        for result in primary_results:
            article_id = result["article"]["id"]
            all_results[article_id] = result

        # Add fallback results (80% weight to prefer primary)
        for result in fallback_results:
            article_id = result["article"]["id"]
            if article_id not in all_results:
                # Apply weight penalty for fallback results
                result["score"] *= 0.8
                all_results[article_id] = result
            # If already in primary, keep the primary (higher weight)

        # Sort by score and return top_k
        merged = sorted(all_results.values(), key=lambda x: x["score"], reverse=True)
        return merged[:top_k]

    def _expand_query_with_catalog(self, query: str) -> str:
        """Expand query by adding relevant synonyms and codes from catalog.

        Strategy (CONSERVATIVE):
        1. Only expand for EXACT matches with article ID or title
        2. Only expand for EXACT code matches
        3. Don't expand for partial synonym matches (too noisy)

        Args:
            query: Original query string

        Returns:
            Expanded query with added terms
        """
        query_lower = query.lower().strip()
        query_normalized = query_lower.replace('_', ' ').replace('-', ' ')
        expansion_terms = set()
        expansion_reason = None

        try:
            # Load catalog data from file
            if not self.catalog.catalog_file.exists():
                return query

            import json
            import re
            catalog_data = json.loads(
                self.catalog.catalog_file.read_text(encoding='utf-8')
            )
            articles = catalog_data.get('articles', {})

            for article_id, article_meta in articles.items():
                # Strategy 1: EXACT article ID match
                id_normalized = article_id.lower().replace('_', ' ').replace('-', ' ')
                if query_normalized == id_normalized:
                    expansion_terms.update(article_meta.get('synonyms', []))
                    expansion_terms.update(article_meta.get('codes', []))
                    expansion_reason = f"Exact ID match: {article_id}"
                    break  # Found exact match, stop searching

                # Strategy 2: Title match (all query words in title, or 80%+ overlap)
                title = article_meta.get('title', '').lower()
                title_clean = re.sub(r'[^\w\s]', '', title).strip()

                # Check if this is a strong title match
                query_words_set = set(query_normalized.split())
                title_words_set = set(title_clean.split())

                if query_words_set <= title_words_set:  # All query words in title
                    # Additional check: title shouldn't have too many extra words
                    extra_words = len(title_words_set - query_words_set)
                    if extra_words <= 3:  # Allow up to 3 extra words in title
                        expansion_terms.update(article_meta.get('synonyms', []))
                        expansion_terms.update(article_meta.get('codes', []))
                        expansion_reason = f"Title match: {article_meta.get('title')}"
                        break  # Found match, stop searching

                # Strategy 3: EXACT code match (Q100, C200, etc.)
                codes = article_meta.get('codes', [])
                for code in codes:
                    # Exact code match (case-insensitive)
                    if query_lower == code.lower():
                        expansion_terms.update(article_meta.get('synonyms', []))
                        expansion_terms.update(codes)
                        expansion_reason = f"Exact code match: {code}"
                        break

            # Remove terms already in original query
            expansion_terms = {t.lower() for t in expansion_terms if t}
            query_keywords = set(query_lower.split())
            expansion_terms = expansion_terms - query_keywords

            # Build expanded query (limit to 3 additional terms for specificity)
            if expansion_terms:
                additional_terms = list(expansion_terms)[:3]
                expanded = f"{query} {' '.join(additional_terms)}"
                print(f"🔍 Query expansion: '{query}' → '{expanded}' ({expansion_reason})")
                return expanded

        except Exception as e:
            print(f"⚠ Query expansion failed: {e}")

        return query  # Return original if expansion fails or no exact match

    def _boost_exact_matches(self, query: str, results: List[Dict]) -> List[Dict]:
        """Boost scores for articles with exact title or ID matches.

        Args:
            query: Original query string
            results: List of retrieval results

        Returns:
            Results with boosted scores for exact matches
        """
        query_lower = query.lower().strip()
        query_normalized = query_lower.replace('_', ' ').replace('-', ' ')

        for result in results:
            article = result["article"]
            article_id = article["id"]
            title = article["title"]

            # Remove emoji and special chars from title
            import re
            title_clean = re.sub(r'[^\w\s]', '', title).lower().strip()
            id_normalized = article_id.replace('_', ' ').replace('-', ' ')

            # Exact title match
            if query_normalized == title_clean:
                old_score = result["score"]
                result["score"] = min(1.0, result["score"] + 0.25)
                print(f"🎯 Exact title match: '{article_id}' boosted {old_score:.3f} → {result['score']:.3f}")

            # Exact ID match
            elif query_normalized == id_normalized:
                old_score = result["score"]
                result["score"] = min(1.0, result["score"] + 0.20)
                print(f"🎯 Exact ID match: '{article_id}' boosted {old_score:.3f} → {result['score']:.3f}")

            # Partial title match (all query words in title)
            elif all(word in title_clean for word in query_normalized.split()):
                old_score = result["score"]
                result["score"] = min(1.0, result["score"] + 0.15)
                print(f"🎯 Partial title match: '{article_id}' boosted {old_score:.3f} → {result['score']:.3f}")

        # Re-sort by boosted scores
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def _extract_specific_terms(self, query: str) -> set:
        """Extract specific technical terms or proper nouns from query.

        These are terms that must appear in the article for it to be relevant.
        Includes:
        - Capitalized words (proper nouns, tech terms like "Docker")
        - Known technical terms (lowercase but specific like "kubernetes", "python")
        - Compound technical terms

        Args:
            query: User query

        Returns:
            Set of specific terms that must be present
        """
        # List of common technical terms (lowercase)
        tech_terms = {
            'docker', 'kubernetes', 'k8s', 'aws', 'azure', 'gcp', 'python', 'java',
            'javascript', 'typescript', 'react', 'vue', 'angular', 'node', 'nodejs',
            'postgres', 'postgresql', 'mysql', 'mongodb', 'redis', 'nginx', 'apache',
            'linux', 'ubuntu', 'centos', 'debian', 'windows', 'macos', 'ios', 'android',
            'github', 'gitlab', 'bitbucket', 'jenkins', 'terraform', 'ansible', 'puppet',
            'elasticsearch', 'kafka', 'rabbitmq', 'graphql', 'rest', 'api',
            'machine learning', 'deep learning', 'artificial intelligence', 'blockchain',
            'cryptocurrency', 'bitcoin', 'ethereum', 'solidity'
        }

        specific_terms = set()
        query_lower = query.lower()

        # Check for multi-word technical terms first
        for term in tech_terms:
            if ' ' in term and term in query_lower:
                specific_terms.add(term)

        # Check each word
        words = query.split()
        for word in words:
            word_lower = word.lower()
            # Skip stop words and common action words
            if word_lower in {'what', 'is', 'are', 'how', 'to', 'do', 'the', 'a', 'an', 'install', 'setup', 'configure', 'use'}:
                continue

            # Check if it's a known technical term
            if word_lower in tech_terms:
                specific_terms.add(word_lower)
            # Check if it's capitalized (proper noun)
            elif word[0].isupper() and len(word) > 2:
                specific_terms.add(word_lower)

        return specific_terms

    def _check_relevance(self, query: str, results: List[Dict]) -> List[Dict]:
        """Check if retrieved articles are actually relevant to the query.

        Adds 'is_relevant' flag and 'relevance_score' to each result.

        NEW: If query contains specific technical terms (like "docker", "kubernetes"),
        the article MUST contain at least one of those terms to be relevant.

        Args:
            query: Original query string
            results: List of retrieval results

        Returns:
            Results with relevance metadata added
        """
        if not results:
            return results

        query_lower = query.lower().strip()

        # Remove common question words and stop words
        stop_words = {'what', 'is', 'are', 'how', 'to', 'do', 'does', 'the', 'a', 'an', 'in', 'on', 'at', 'for', 'of'}
        query_words = set(query_lower.split()) - stop_words

        # Extract specific terms that must be present
        specific_terms = self._extract_specific_terms(query)

        import re

        for result in results:
            article = result["article"]
            title = article["title"]
            content = article.get("content", "")

            # Clean title and content
            title_clean = re.sub(r'[^\w\s]', '', title).lower()
            content_lower = content.lower()  # Check full content for specific terms

            # Calculate relevance score based on keyword overlap
            title_words = set(title_clean.split())

            # Check how many query keywords appear in title
            title_overlap = len(query_words & title_words)
            title_relevance = title_overlap / len(query_words) if query_words else 0

            # Check how many query keywords appear in content (first 500 chars for general check)
            content_snippet = content_lower[:500]
            content_overlap = sum(1 for word in query_words if word in content_snippet)
            content_relevance = content_overlap / len(query_words) if query_words else 0

            # Combined relevance score
            relevance_score = (title_relevance * 0.6) + (content_relevance * 0.4)

            # Mark as relevant if:
            # 1. Decent relevance score (>= 0.2), OR
            # 2. Semantic score is high (>= 0.70), OR
            # 3. Article ID/title contains query keywords (for exact matches)
            article_id = article["id"]
            id_match = any(word in article_id.lower() for word in query_words)
            title_match = relevance_score > 0

            is_relevant = (
                relevance_score >= 0.2 or
                result["score"] >= 0.70 or
                (id_match and result["score"] >= 0.50)
            )

            # NEW: If query has specific technical terms, article MUST contain them
            if specific_terms and is_relevant:
                has_specific_term = any(term in content_lower for term in specific_terms)
                if not has_specific_term:
                    is_relevant = False
                    print(f"⚠ Missing specific term: '{article['id']}' lacks {specific_terms} (relevance={relevance_score:.3f}, score={result['score']:.3f})")

            # Add metadata
            result["relevance_score"] = round(relevance_score, 3)
            result["is_relevant"] = is_relevant

            if not is_relevant and not specific_terms:
                print(f"⚠ Low relevance: '{article['id']}' (relevance={relevance_score:.3f}, score={result['score']:.3f})")

        return results

    def retrieve_by_id(
        self,
        article_id: str,
        include_related: bool = True
    ) -> Optional[Dict]:
        """Retrieve a specific article by ID.

        Args:
            article_id: Article ID to retrieve
            include_related: Whether to include related articles

        Returns:
            Article result with content and metadata, or None if not found
        """
        try:
            article = self.catalog.get_article(article_id)

            result = {
                "article": article,
                "score": 1.0,  # Direct lookup, perfect match
                "related": {}
            }

            if include_related:
                result["related"] = self._get_related_articles(article_id)

            return result

        except Exception as e:
            print(f"⚠ Failed to retrieve article '{article_id}': {e}")
            return None

    def retrieve_by_ids(
        self,
        article_ids: List[str],
        include_related: bool = False
    ) -> List[Dict]:
        """Retrieve multiple articles by IDs.

        Args:
            article_ids: List of article IDs
            include_related: Whether to include related articles

        Returns:
            List of article results
        """
        results = []
        for article_id in article_ids:
            result = self.retrieve_by_id(article_id, include_related)
            if result:
                results.append(result)
        return results

    def _build_filter(self, classification: Optional[Dict]) -> Optional[Dict]:
        """Build ChromaDB metadata filter from classification.

        Strategy: Intent is PRIMARY filter (always use), category is OPTIONAL refinement (skip if "unknown").

        Args:
            classification: Query classification

        Returns:
            ChromaDB where filter dictionary, or None if no filters
        """
        if not classification:
            return None

        filters = []

        # Add intent filter (primary - always use if available)
        intent = classification.get("intent")
        if intent and intent in ["do", "learn", "trouble"]:
            filters.append({"intent": intent})

        # Add category filter (secondary - only if NOT "unknown")
        category = classification.get("category")
        if category and category in ["application", "data"]:  # Skips "unknown"
            filters.append({"category": category})

        # Return None if no filters
        if not filters:
            return None

        # If single filter, return it directly
        if len(filters) == 1:
            return filters[0]

        # Multiple filters: use $and operator
        return {"$and": filters}

    def _semantic_search(
        self,
        query: str,
        where_filter: Optional[Dict],
        top_k: int
    ) -> Dict:
        """Perform semantic search in ChromaDB.

        Args:
            query: Query string
            where_filter: Metadata filter
            top_k: Number of results

        Returns:
            ChromaDB query results
        """
        # Query ChromaDB with metadata filter
        # Get more results than needed (we'll deduplicate by article_id)
        n_results = top_k * 3

        try:
            # Generate embedding using Cloudflare (same as vectorization)
            query_embedding = get_embeddings([query])[0]

            # Query with pre-computed embedding
            results = self.chroma.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where_filter
            )
            return results

        except Exception as e:
            print(f"⚠ ChromaDB query failed: {e}")
            # Return empty results
            return {
                "ids": [[]],
                "distances": [[]],
                "metadatas": [[]]
            }

    def _deduplicate_articles(self, search_results: Dict) -> List[tuple]:
        """Deduplicate chunks to get unique articles with best scores.

        Args:
            search_results: ChromaDB query results

        Returns:
            List of (article_id, score) tuples, sorted by score
        """
        if not search_results["ids"] or not search_results["ids"][0]:
            return []

        # Collect article IDs with their best scores
        article_scores = {}

        ids = search_results["ids"][0]
        distances = search_results["distances"][0]
        metadatas = search_results["metadatas"][0]

        for chunk_id, distance, metadata in zip(ids, distances, metadatas):
            article_id = metadata.get("article_id")

            if not article_id:
                continue

            # Convert distance to similarity score (lower distance = higher similarity)
            # ChromaDB uses L2 distance, so we convert: score = 1 / (1 + distance)
            score = 1.0 / (1.0 + distance)

            # Keep best score for this article
            if article_id not in article_scores or score > article_scores[article_id]:
                article_scores[article_id] = score

        # Sort by score (descending)
        sorted_articles = sorted(
            article_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return sorted_articles

    def _get_related_articles(self, article_id: str) -> Dict:
        """Get related articles (parent, children, see-also).

        Args:
            article_id: Article ID

        Returns:
            Dictionary with related articles:
            {
                "parent": {...} or None,
                "children": [...],
                "see_also": [...]
            }
        """
        related = {
            "parent": None,
            "children": [],
            "see_also": []
        }

        try:
            # Get related article IDs
            related_ids = self.catalog.get_related_articles(article_id)

            # Load parent
            if related_ids.get("parent_id"):
                try:
                    parent = self.catalog.get_article(related_ids["parent_id"])
                    related["parent"] = parent
                except Exception:
                    pass

            # Load children
            for child_id in related_ids.get("children_ids", []):
                try:
                    child = self.catalog.get_article(child_id)
                    related["children"].append(child)
                except Exception:
                    pass

            # Load see-also
            for see_also_id in related_ids.get("see_also_ids", []):
                try:
                    see_also = self.catalog.get_article(see_also_id)
                    related["see_also"].append(see_also)
                except Exception:
                    pass

        except Exception as e:
            print(f"⚠ Failed to load related articles for '{article_id}': {e}")

        return related

    def get_all_articles(self) -> List[Dict]:
        """Get all articles from catalog.

        Returns:
            List of all articles
        """
        try:
            catalog_file = self.catalog.catalog_file
            if not catalog_file.exists():
                return []

            import json
            catalog_data = json.loads(catalog_file.read_text(encoding='utf-8'))

            articles = []
            for article_id in catalog_data.get("articles", {}).keys():
                try:
                    article = self.catalog.get_article(article_id)
                    articles.append(article)
                except Exception:
                    continue

            return articles

        except Exception as e:
            print(f"⚠ Failed to load all articles: {e}")
            return []


def main():
    """CLI for testing catalog retriever."""
    import argparse
    import chromadb

    parser = argparse.ArgumentParser(
        description="Test catalog retriever with semantic search"
    )

    parser.add_argument(
        "query",
        nargs="?",
        help="Query to search (or use --interactive)"
    )

    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=Path("output/catalog"),
        help="Catalog directory (default: output/catalog)"
    )

    parser.add_argument(
        "--index-dir",
        type=Path,
        default=Path("output/vector_index"),
        help="Vector index directory (default: output/vector_index)"
    )

    parser.add_argument(
        "--collection",
        default="manual_chunks",
        help="ChromaDB collection name (default: manual_chunks)"
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of articles to retrieve (default: 3)"
    )

    parser.add_argument(
        "--no-related",
        action="store_true",
        help="Don't include related articles"
    )

    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive mode"
    )

    args = parser.parse_args()

    # Initialize catalog builder
    catalog_builder = CatalogBuilder(args.catalog_dir)

    # Check if catalog exists
    if not catalog_builder.catalog_file.exists():
        print(f"✗ Error: Catalog not found at {catalog_builder.catalog_file}")
        print("Please run build_catalog.py first.")
        return 1

    # Initialize ChromaDB
    try:
        client = chromadb.PersistentClient(path=str(args.index_dir))
        collection = client.get_collection(args.collection)
    except Exception as e:
        print(f"✗ Error: Failed to connect to ChromaDB: {e}")
        print("Please run vectorize_catalog.py first.")
        return 1

    # Initialize retriever
    retriever = CatalogRetriever(
        collection,
        catalog_builder,
        default_top_k=args.top_k,
        include_related=not args.no_related
    )

    if args.interactive:
        print("\n" + "="*70)
        print("Catalog Retriever - Interactive Mode")
        print("="*70)
        print("Enter queries to search (Ctrl+C or 'quit' to exit)\n")

        try:
            while True:
                query = input("Query: ").strip()

                if not query or query.lower() in ['quit', 'exit', 'q']:
                    break

                print("\nSearching...")
                results = retriever.retrieve(query, top_k=args.top_k)

                print(f"\nFound {len(results)} articles:\n")

                for i, result in enumerate(results, 1):
                    article = result["article"]
                    score = result["score"]
                    related = result["related"]

                    print(f"{i}. {article['title']}")
                    print(f"   ID: {article['id']}")
                    print(f"   Score: {score:.3f}")
                    print(f"   Intent: {article['intent']}, Category: {article['category']}")

                    if related["parent"]:
                        print(f"   Parent: {related['parent']['title']}")

                    if related["children"]:
                        print(f"   Children: {len(related['children'])} articles")

                    if related["see_also"]:
                        print(f"   See also: {len(related['see_also'])} articles")

                    print()

        except KeyboardInterrupt:
            print("\n\nExiting...")

    elif args.query:
        print("\n" + "="*70)
        print("Catalog Retriever")
        print("="*70)
        print(f"Query: {args.query}\n")

        results = retriever.retrieve(args.query, top_k=args.top_k)

        print(f"Found {len(results)} articles:\n")

        for i, result in enumerate(results, 1):
            article = result["article"]
            score = result["score"]
            related = result["related"]

            print(f"{i}. {article['title']}")
            print(f"   ID: {article['id']}")
            print(f"   Score: {score:.3f}")
            print(f"   Intent: {article['intent']}, Category: {article['category']}")
            print(f"   Content: {article['content'][:200]}...")

            if related["parent"]:
                print(f"   Parent: {related['parent']['title']}")

            if related["children"]:
                print(f"   Children: {', '.join([c['title'] for c in related['children']])}")

            if related["see_also"]:
                print(f"   See also: {', '.join([s['title'] for s in related['see_also']])}")

            print()

        print("="*70 + "\n")

    else:
        # Show catalog stats
        print("\n" + "="*70)
        print("Catalog Retriever - Statistics")
        print("="*70)

        all_articles = retriever.get_all_articles()
        print(f"Total articles: {len(all_articles)}")
        print(f"Vector index: {args.index_dir}")
        print(f"Collection: {args.collection}")
        print(f"Total vectors: {collection.count()}")

        print("\nArticles by intent:")
        intent_counts = {}
        for article in all_articles:
            intent = article.get("intent", "unknown")
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
        for intent, count in sorted(intent_counts.items()):
            print(f"  {intent}: {count}")

        print("\nArticles by category:")
        category_counts = {}
        for article in all_articles:
            category = article.get("category", "unknown")
            category_counts[category] = category_counts.get(category, 0) + 1
        for category, count in sorted(category_counts.items()):
            print(f"  {category}: {count}")

        print("\n" + "="*70 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
