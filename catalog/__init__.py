"""
Catalog module for ManualBook article management.

This module provides functionality for:
- Parsing metadata from markdown files
- Extracting articles based on heading structure
- Building file-based article catalog
- Querying and retrieving articles

File structure:
    catalog/
        articles/           - Individual article .md files
        catalog.json        - Article index and metadata
        relationships.json  - Article relationship graph

Metadata format (in markdown):
    <!--METADATA
    intent: do            # do, learn, trouble
    id: article_id        # unique identifier
    category: application # application, data
    see:                  # optional related articles
        - other_article_id
        - another_id
    -->

Usage:
    from catalog import CatalogBuilder

    # Build catalog from markdown
    builder = CatalogBuilder(Path("output/catalog"))
    stats = builder.build_from_markdown(Path("md/manual.md"))

    # Query articles
    article = builder.get_article("editing_palette")
    related = builder.get_related_articles("editing_palette")
    do_articles = builder.search_articles(intent="do")
"""

from .metadata_parser import parse_metadata, extract_metadata_block, MetadataError
from .article_extractor import Article, extract_articles, build_relationship_graph
from .builder import CatalogBuilder

__all__ = [
    "parse_metadata",
    "extract_metadata_block",
    "MetadataError",
    "Article",
    "extract_articles",
    "build_relationship_graph",
    "CatalogBuilder",
]

__version__ = "1.0.0"
