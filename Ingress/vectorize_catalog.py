#!/usr/bin/env python3
"""
Vectorize articles from catalog into ChromaDB.

This script reads articles from the catalog (instead of raw chunks) and:
1. Loads complete articles from catalog
2. Chunks articles intelligently (by paragraph)
3. Generates embeddings using Cloudflare/OpenAI
4. Stores in ChromaDB with article_id metadata
5. Enables retrieval by article_id and metadata filtering

Usage:
    python Ingress/vectorize_catalog.py
    python Ingress/vectorize_catalog.py --reset
    python Ingress/vectorize_catalog.py --batch-size 10
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List

# Load environment variables
try:
    from dotenv import load_dotenv
    BASE_DIR_TEMP = Path(__file__).resolve().parents[1]
    env_path = BASE_DIR_TEMP / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

try:
    import chromadb
    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'chromadb'. Install it with 'pip install chromadb' and retry."
    ) from exc

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import CatalogBuilder
from llm import get_embeddings, get_gloss, LLMServiceError


BASE_DIR = Path(__file__).resolve().parents[1]
CATALOG_DIR = BASE_DIR / "output" / "catalog"
INDEX_DIR = BASE_DIR / "output" / "vector_index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_COLLECTION = os.environ.get("VECTOR_COLLECTION", "manual_chunks")


class ArticleChunker:
    """Intelligent article chunking for vectorization."""

    def __init__(
        self,
        min_chunk_size: int = 100,
        max_chunk_size: int = 1000,
        whole_article_threshold: int = 800
    ):
        """Initialize chunker.

        Args:
            min_chunk_size: Minimum chunk size (chars)
            max_chunk_size: Maximum chunk size (chars)
            whole_article_threshold: If article < this, don't chunk it
        """
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.whole_article_threshold = whole_article_threshold

    def chunk_article(self, article: Dict) -> List[Dict]:
        """Chunk article into smaller pieces.

        Args:
            article: Article data from catalog

        Returns:
            List of chunks, each with {text, chunk_index, metadata}
        """
        content = article['content']

        # Remove metadata block from content
        content_no_meta = self._remove_metadata_block(content)

        # If article is small, return whole article as single chunk
        if len(content_no_meta) <= self.whole_article_threshold:
            return [{
                'text': content_no_meta,
                'chunk_index': 0,
                'is_whole_article': True
            }]

        # Split by paragraphs
        paragraphs = self._split_paragraphs(content_no_meta)

        # Group paragraphs into chunks
        chunks = []
        current_chunk = []
        current_size = 0

        for para in paragraphs:
            para_size = len(para)

            # Skip tiny paragraphs
            if para_size < 20:
                continue

            # If adding this paragraph exceeds max size, save current chunk
            if current_size + para_size > self.max_chunk_size and current_chunk:
                chunk_text = '\n\n'.join(current_chunk)
                if len(chunk_text) >= self.min_chunk_size:
                    chunks.append({
                        'text': chunk_text,
                        'chunk_index': len(chunks),
                        'is_whole_article': False
                    })
                current_chunk = []
                current_size = 0

            # Add paragraph to current chunk
            current_chunk.append(para)
            current_size += para_size

        # Save last chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            if len(chunk_text) >= self.min_chunk_size:
                chunks.append({
                    'text': chunk_text,
                    'chunk_index': len(chunks),
                    'is_whole_article': False
                })

        return chunks if chunks else [{
            'text': content_no_meta,
            'chunk_index': 0,
            'is_whole_article': True
        }]

    def _remove_metadata_block(self, content: str) -> str:
        """Remove metadata block from content."""
        pattern = r'<!--\s*METADATA\s*\n.*?\n\s*-->\s*\n?'
        return re.sub(pattern, '', content, count=1, flags=re.DOTALL | re.IGNORECASE)

    def _split_paragraphs(self, content: str) -> List[str]:
        """Split content into paragraphs."""
        # Split by double newline (paragraph separator)
        paragraphs = re.split(r'\n\n+', content)
        return [p.strip() for p in paragraphs if p.strip()]


def build_chunk_metadata(article: Dict, chunk_index: int, total_chunks: int) -> Dict:
    """Build metadata for a chunk.

    Args:
        article: Article data from catalog
        chunk_index: Index of this chunk
        total_chunks: Total number of chunks for this article

    Returns:
        Metadata dictionary for ChromaDB
    """
    metadata = {
        # Article identification
        "article_id": article['id'],
        "title": article['title'],

        # Classification
        "intent": article['intent'],
        "category": article['category'],

        # Chunk info
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,

        # Relationships
        "parent_id": article.get('parent_id') or "",
        "has_children": len(article.get('children_ids', [])) > 0,

        # Content info
        "heading_level": article.get('heading_level', 1),
    }

    # Add see_also as semicolon-separated string
    see_also = article.get('see_also_ids', [])
    if see_also:
        metadata["see_also_ids"] = ";".join(see_also)

    # Add images as semicolon-separated string
    images = article.get('images', [])
    if images:
        metadata["images"] = ";".join(images)

    return metadata


def vectorize_catalog(
    catalog_builder: CatalogBuilder,
    collection: Collection,
    batch_size: int = 8,
    pause: float = 0.1
) -> Dict:
    """Vectorize all articles from catalog.

    Args:
        catalog_builder: CatalogBuilder instance
        collection: ChromaDB collection
        batch_size: Number of chunks to process per batch
        pause: Pause between batches (seconds)

    Returns:
        Statistics dictionary
    """
    # Read catalog
    catalog_file = catalog_builder.catalog_file
    if not catalog_file.exists():
        raise FileNotFoundError(f"Catalog not found: {catalog_file}")

    import json
    catalog_data = json.loads(catalog_file.read_text(encoding='utf-8'))
    article_ids = list(catalog_data['articles'].keys())

    print(f"\n{'='*70}")
    print(f"Vectorizing {len(article_ids)} articles from catalog")
    print(f"{'='*70}\n")

    chunker = ArticleChunker()

    total_chunks = 0
    processed_articles = 0
    failed_articles = 0

    # Batch processing
    all_chunks = []
    all_ids = []
    all_metadatas = []
    all_glosses = []

    start_time = time.time()

    for idx, article_id in enumerate(article_ids, 1):
        try:
            # Load article
            article = catalog_builder.get_article(article_id)

            # Chunk article
            chunks = chunker.chunk_article(article)

            # Process each chunk
            for chunk_data in chunks:
                chunk_id = f"{article_id}__chunk_{chunk_data['chunk_index']}"
                chunk_text = chunk_data['text']

                # Build metadata
                metadata = build_chunk_metadata(
                    article,
                    chunk_data['chunk_index'],
                    len(chunks)
                )

                # Generate gloss (summary)
                try:
                    gloss = get_gloss(chunk_text)
                except Exception as e:
                    print(f"  ⚠ Gloss generation failed for {chunk_id}: {e}")
                    gloss = None

                # Augment text with gloss
                augmented_text = chunk_text
                if gloss:
                    augmented_text = f"{chunk_text.strip()}\n\nSummary: {gloss.strip()}"
                    metadata["gloss"] = gloss

                all_chunks.append(augmented_text)
                all_ids.append(chunk_id)
                all_metadatas.append(metadata)
                all_glosses.append(gloss)
                total_chunks += 1

            processed_articles += 1

            # Progress update
            if idx % 5 == 0 or idx == len(article_ids):
                progress = (idx / len(article_ids)) * 100
                elapsed = time.time() - start_time
                print(f"Progress: [{idx}/{len(article_ids)}] {progress:.1f}% | "
                      f"Articles: {processed_articles} | Chunks: {total_chunks} | "
                      f"Elapsed: {elapsed:.1f}s")

        except Exception as e:
            print(f"  ✗ Failed to process article '{article_id}': {e}")
            failed_articles += 1

    # Now vectorize all chunks in batches
    print(f"\n{'='*70}")
    print(f"Generating embeddings for {total_chunks} chunks...")
    print(f"{'='*70}\n")

    batch_count = (total_chunks + batch_size - 1) // batch_size

    for batch_idx in range(0, total_chunks, batch_size):
        batch_end = min(batch_idx + batch_size, total_chunks)
        batch_texts = all_chunks[batch_idx:batch_end]
        batch_ids = all_ids[batch_idx:batch_end]
        batch_metas = all_metadatas[batch_idx:batch_end]

        batch_num = (batch_idx // batch_size) + 1
        progress = (batch_num / batch_count) * 100
        print(f"Batch {batch_num}/{batch_count} ({progress:.1f}%): "
              f"Embedding {len(batch_texts)} chunks...")

        try:
            # Generate embeddings
            embeddings = get_embeddings(batch_texts)

            # Store in ChromaDB
            collection.upsert(
                ids=batch_ids,
                embeddings=embeddings,
                documents=batch_texts,
                metadatas=batch_metas
            )

            print(f"  ✓ Stored {len(batch_texts)} chunks")

            # Pause to avoid rate limiting
            if batch_idx + batch_size < total_chunks:
                time.sleep(pause)

        except Exception as e:
            print(f"  ✗ Batch {batch_num} failed: {e}")

    total_time = time.time() - start_time

    stats = {
        "total_articles": len(article_ids),
        "processed_articles": processed_articles,
        "failed_articles": failed_articles,
        "total_chunks": total_chunks,
        "avg_chunks_per_article": total_chunks / processed_articles if processed_articles > 0 else 0,
        "total_time": total_time,
        "chunks_per_second": total_chunks / total_time if total_time > 0 else 0
    }

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Vectorize articles from catalog into ChromaDB"
    )

    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=CATALOG_DIR,
        help=f"Catalog directory (default: {CATALOG_DIR})"
    )

    parser.add_argument(
        "--index-dir",
        type=Path,
        default=INDEX_DIR,
        help=f"ChromaDB index directory (default: {INDEX_DIR})"
    )

    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help=f"ChromaDB collection name (default: {DEFAULT_COLLECTION})"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Chunks per batch (default: 8)"
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset collection before vectorizing"
    )

    parser.add_argument(
        "--pause",
        type=float,
        default=0.1,
        help="Pause between batches (default: 0.1s)"
    )

    args = parser.parse_args()

    print("\n" + "="*70)
    print("Catalog Vectorization")
    print("="*70)
    print(f"Catalog: {args.catalog_dir}")
    print(f"Index: {args.index_dir}")
    print(f"Collection: {args.collection}")
    print(f"Batch size: {args.batch_size}")
    print("="*70)

    # Initialize catalog builder
    catalog_builder = CatalogBuilder(args.catalog_dir)

    # Check if catalog exists
    if not catalog_builder.catalog_file.exists():
        print(f"\n✗ Error: Catalog not found at {catalog_builder.catalog_file}")
        print("Please run build_catalog.py first to create the catalog.")
        return 1

    # Initialize ChromaDB
    args.index_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(args.index_dir))

    # Get or create collection
    if args.reset:
        try:
            client.delete_collection(args.collection)
            print(f"✓ Reset collection: {args.collection}")
        except Exception:
            pass

    collection = client.get_or_create_collection(name=args.collection)

    # Vectorize
    try:
        stats = vectorize_catalog(
            catalog_builder,
            collection,
            batch_size=args.batch_size,
            pause=args.pause
        )

        print("\n" + "="*70)
        print("VECTORIZATION COMPLETE")
        print("="*70)
        print(f"  Total articles: {stats['total_articles']}")
        print(f"  Processed: {stats['processed_articles']}")
        print(f"  Failed: {stats['failed_articles']}")
        print(f"  Total chunks: {stats['total_chunks']}")
        print(f"  Avg chunks/article: {stats['avg_chunks_per_article']:.1f}")
        print(f"  Total time: {stats['total_time']:.1f}s ({stats['total_time']/60:.1f} min)")
        print(f"  Speed: {stats['chunks_per_second']:.2f} chunks/sec")
        print("="*70)
        print(f"\nVector index: {args.index_dir}")
        print(f"Collection: {args.collection}")
        print(f"Total vectors: {collection.count()}")
        print("\nNext steps:")
        print("  1. Test semantic search with metadata filters")
        print("  2. Integrate with app.py for catalog-based retrieval")
        print("="*70 + "\n")

        return 0

    except Exception as e:
        print(f"\n✗ Error during vectorization: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
