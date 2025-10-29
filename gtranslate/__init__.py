"""
Google services for ManualBook system.

This module provides centralized access to Google services including translation.
"""

from .translate_service import translate_text

__all__ = ["translate_text"]
