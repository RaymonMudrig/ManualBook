"""
Catalog builder for ManualBook.

Builds a file-based catalog from extracted articles:
- Individual .md files for each article in catalog/articles/
- Image directories copied to catalog/articles/
- catalog.json for index and metadata
- relationships.json for article relationships
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .article_extractor import Article, extract_articles, build_relationship_graph


class CatalogBuilder:
    """Builds and manages file-based article catalog."""

    def __init__(self, catalog_dir: Path):
        """Initialize catalog builder.

        Args:
            catalog_dir: Directory to store catalog (e.g., output/catalog)
        """
        self.catalog_dir = Path(catalog_dir)
        self.articles_dir = self.catalog_dir / "articles"
        self.catalog_file = self.catalog_dir / "catalog.json"
        self.relationships_file = self.catalog_dir / "relationships.json"

        # Create directories
        self.articles_dir.mkdir(parents=True, exist_ok=True)

    def build_from_markdown(self, source_md_path: Path, clean_existing: bool = False) -> Dict:
        """Build catalog from a markdown file.

        Args:
            source_md_path: Path to source markdown file
            clean_existing: If True, remove existing catalog first

        Returns:
            Dictionary with build statistics

        Example:
            >>> builder = CatalogBuilder(Path("output/catalog"))
            >>> stats = builder.build_from_markdown(Path("md/manual.md"))
            >>> print(f"Extracted {stats['articles_count']} articles")
        """
        if clean_existing:
            self._clean_catalog()

        # Read source markdown
        if not source_md_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_md_path}")

        content = source_md_path.read_text(encoding='utf-8')

        # Extract articles
        articles = extract_articles(content, str(source_md_path))

        if not articles:
            return {
                "articles_count": 0,
                "message": "No articles with metadata found in source file"
            }

        # Save articles
        for article in articles:
            self._save_article(article)

        # Copy related images
        self._copy_images(source_md_path)

        # Build and save catalog
        catalog_data = self._build_catalog_data(articles, source_md_path)
        self._save_catalog(catalog_data)

        # Build and save relationships
        relationships = build_relationship_graph(articles)
        self._save_relationships(relationships)

        stats = {
            "articles_count": len(articles),
            "source_file": str(source_md_path),
            "catalog_dir": str(self.catalog_dir),
            "timestamp": datetime.now().isoformat(),
            "by_intent": self._count_by_field(articles, 'intent'),
            "by_category": self._count_by_field(articles, 'category'),
        }

        return stats

    def _save_article(self, article: Article) -> None:
        """Save article as individual .md file.

        Args:
            article: Article object to save
        """
        # Create filename from article ID
        filename = f"{article.id}.md"
        filepath = self.articles_dir / filename

        # Save full content (includes metadata)
        filepath.write_text(article.content, encoding='utf-8')

    def _build_catalog_data(self, articles: List[Article], source_file: Path) -> Dict:
        """Build catalog index data.

        Args:
            articles: List of Article objects
            source_file: Source markdown file

        Returns:
            Catalog data dictionary
        """
        catalog = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "source_file": str(source_file),
            "total_articles": len(articles),
            "articles": {}
        }

        for article in articles:
            catalog["articles"][article.id] = {
                "title": article.title,
                "intent": article.intent,
                "category": article.category,
                "file": f"articles/{article.id}.md",
                "heading_level": article.heading_level,
                "parent_id": article.parent_id,
                "children_ids": article.children_ids,
                "see_also_ids": article.see_also_ids,
                "images": article.images,
                "synonyms": article.synonyms,
                "codes": article.codes,
                "word_count": len(article.content.split()),
                "char_count": len(article.content),
            }

        return catalog

    def _save_catalog(self, catalog_data: Dict) -> None:
        """Save catalog index to JSON.

        Args:
            catalog_data: Catalog data dictionary
        """
        self.catalog_file.write_text(
            json.dumps(catalog_data, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def _save_relationships(self, relationships: Dict) -> None:
        """Save relationship graph to JSON.

        Args:
            relationships: Relationship graph dictionary
        """
        # Add metadata
        relationships["version"] = "1.0"
        relationships["created_at"] = datetime.now().isoformat()

        self.relationships_file.write_text(
            json.dumps(relationships, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def _clean_catalog(self) -> None:
        """Remove existing catalog files."""
        if self.articles_dir.exists():
            shutil.rmtree(self.articles_dir)
        self.articles_dir.mkdir(parents=True, exist_ok=True)

        if self.catalog_file.exists():
            self.catalog_file.unlink()

        if self.relationships_file.exists():
            self.relationships_file.unlink()

    def _copy_images(self, source_md_path: Path) -> None:
        """Copy image directories from source directory to catalog articles directory.

        Args:
            source_md_path: Path to source markdown file
        """
        # Get source directory (where the .md file is)
        source_dir = source_md_path.parent

        # Find all image directories (directories ending with '_images')
        image_dirs = [d for d in source_dir.iterdir() if d.is_dir() and d.name.endswith('_images')]

        if not image_dirs:
            return

        # Copy each image directory to catalog/articles/
        for image_dir in image_dirs:
            dest_dir = self.articles_dir / image_dir.name

            # Remove existing destination if it exists
            if dest_dir.exists():
                shutil.rmtree(dest_dir)

            # Copy the entire directory
            shutil.copytree(image_dir, dest_dir)
            print(f"  ✓ Copied images: {image_dir.name}/")

    def _count_by_field(self, articles: List[Article], field: str) -> Dict[str, int]:
        """Count articles by a specific field.

        Args:
            articles: List of Article objects
            field: Field name to count by

        Returns:
            Dictionary of counts
        """
        counts = {}
        for article in articles:
            value = getattr(article, field)
            counts[value] = counts.get(value, 0) + 1
        return counts

    def get_article(self, article_id: str) -> Dict:
        """Get article by ID from catalog.

        Args:
            article_id: Article identifier

        Returns:
            Article data dictionary

        Raises:
            FileNotFoundError: If article not found
        """
        # Load catalog
        if not self.catalog_file.exists():
            raise FileNotFoundError("Catalog not found. Build catalog first.")

        catalog = json.loads(self.catalog_file.read_text(encoding='utf-8'))

        if article_id not in catalog["articles"]:
            raise KeyError(f"Article '{article_id}' not found in catalog")

        # Get article metadata
        article_meta = catalog["articles"][article_id]

        # Load article content
        article_file = self.catalog_dir / article_meta["file"]
        if not article_file.exists():
            raise FileNotFoundError(f"Article file not found: {article_file}")

        content = article_file.read_text(encoding='utf-8')

        return {
            **article_meta,
            "id": article_id,
            "content": content
        }

    def search_articles(self, **filters) -> List[Dict]:
        """Search articles by filters.

        Args:
            **filters: Search filters (intent, category, parent_id, etc.)

        Returns:
            List of matching article metadata

        Example:
            >>> builder.search_articles(intent='do', category='application')
            [{'id': 'editing_palette', 'title': 'Editing Palette', ...}]
        """
        if not self.catalog_file.exists():
            return []

        catalog = json.loads(self.catalog_file.read_text(encoding='utf-8'))

        results = []
        for article_id, article_meta in catalog["articles"].items():
            # Check if all filters match
            if all(article_meta.get(k) == v for k, v in filters.items()):
                results.append({
                    "id": article_id,
                    **article_meta
                })

        return results

    def get_related_articles(self, article_id: str) -> Dict[str, List[Dict]]:
        """Get all articles related to given article.

        Args:
            article_id: Article identifier

        Returns:
            Dictionary with different types of relationships:
            {
                "parent": {...},
                "children": [{...}, ...],
                "see_also": [{...}, ...],
                "siblings": [{...}, ...]
            }
        """
        if not self.relationships_file.exists():
            return {}

        relationships = json.loads(self.relationships_file.read_text(encoding='utf-8'))

        if article_id not in relationships["articles"]:
            return {}

        article_rel = relationships["articles"][article_id]
        catalog = json.loads(self.catalog_file.read_text(encoding='utf-8'))

        related = {
            "parent": None,
            "children": [],
            "see_also": [],
            "siblings": []
        }

        # Get parent
        if article_rel["parent"]:
            parent_id = article_rel["parent"]
            if parent_id in catalog["articles"]:
                related["parent"] = {
                    "id": parent_id,
                    **catalog["articles"][parent_id]
                }

                # Get siblings (other children of same parent)
                parent_rel = relationships["articles"][parent_id]
                for sibling_id in parent_rel["children"]:
                    if sibling_id != article_id:
                        related["siblings"].append({
                            "id": sibling_id,
                            **catalog["articles"][sibling_id]
                        })

        # Get children
        for child_id in article_rel["children"]:
            if child_id in catalog["articles"]:
                related["children"].append({
                    "id": child_id,
                    **catalog["articles"][child_id]
                })

        # Get see also
        for see_id in article_rel["see_also"]:
            if see_id in catalog["articles"]:
                related["see_also"].append({
                    "id": see_id,
                    **catalog["articles"][see_id]
                })

        return related


if __name__ == "__main__":
    # Test the builder
    print("Testing Catalog Builder\n" + "=" * 50)

    # Create test markdown
    test_md = Path("test_manual.md")
    test_md.write_text("""<!--METADATA
intent: learn
id: palettes
category: application
-->
# Palettes

Color palette management system.

<!--METADATA
intent: do
id: editing_palette
category: application
see:
    - color_settings
-->
## Editing Palettes

How to edit existing palettes.

<!--METADATA
intent: do
id: creating_palette
category: application
-->
## Creating Palettes

How to create new palettes.

<!--METADATA
intent: learn
id: data_types
category: data
-->
# Data Types

Understanding market data types.
""", encoding='utf-8')

    try:
        # Build catalog
        builder = CatalogBuilder(Path("test_catalog"))
        stats = builder.build_from_markdown(test_md, clean_existing=True)

        print("\n✓ Catalog built successfully!")
        print(f"  Articles: {stats['articles_count']}")
        print(f"  By Intent: {stats['by_intent']}")
        print(f"  By Category: {stats['by_category']}")

        # Test search
        print("\n✓ Testing search...")
        do_articles = builder.search_articles(intent='do')
        print(f"  Found {len(do_articles)} 'do' articles")

        # Test get article
        print("\n✓ Testing get article...")
        article = builder.get_article('editing_palette')
        print(f"  Title: {article['title']}")
        print(f"  Content length: {article['char_count']} chars")

        # Test relationships
        print("\n✓ Testing relationships...")
        related = builder.get_related_articles('editing_palette')
        print(f"  Parent: {related['parent']['id'] if related['parent'] else 'None'}")
        print(f"  Siblings: {len(related['siblings'])}")
        print(f"  See Also: {len(related['see_also'])}")

        print("\n" + "=" * 50)
        print("✓ All tests passed!")

    finally:
        # Cleanup
        test_md.unlink(missing_ok=True)
        shutil.rmtree("test_catalog", ignore_errors=True)
