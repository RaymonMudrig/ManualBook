"""
LLM service module for ManualBook system.

This module provides centralized access to LLM operations including
embeddings, completions, translations, and glossing.
"""

from .service import (
    LLMServiceError,
    get_completion,
    get_embeddings,
    get_gloss,
    get_provider_info,
    translate_text,
    generate_answer,
    test_connection,
)

__all__ = [
    "LLMServiceError",
    "get_completion",
    "get_embeddings",
    "get_gloss",
    "get_provider_info",
    "translate_text",
    "generate_answer",
    "test_connection",
]
