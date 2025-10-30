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
        include_related: Optional[bool] = None
    ) -> List[Dict]:
        """Retrieve articles for a query.

        Args:
            query: User query string
            classification: Query classification (intent, category, topics)
            top_k: Number of articles to retrieve (default: self.default_top_k)
            include_related: Whether to include related articles (default: self.include_related)

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

        # Step 1: Build metadata filter from classification
        where_filter = self._build_filter(classification)

        # Step 2: Semantic search with metadata filtering
        search_results = self._semantic_search(query, where_filter, top_k)

        # Step 3: Get unique article IDs (deduplicate chunks)
        article_ids_with_scores = self._deduplicate_articles(search_results)

        # Step 4: Retrieve complete articles from catalog
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
