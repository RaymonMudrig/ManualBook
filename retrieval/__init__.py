"""
Retrieval package for catalog-based semantic search.

Components:
- query_classifier: Classify user queries by intent and category
- catalog_retriever: Retrieve complete articles with metadata filtering
"""

from .query_classifier import QueryClassifier
from .catalog_retriever import CatalogRetriever

__all__ = ['QueryClassifier', 'CatalogRetriever']
