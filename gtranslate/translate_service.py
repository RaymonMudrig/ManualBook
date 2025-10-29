"""
Centralized Google Translate service for ManualBook system.

This module provides a simple, reliable translation service using Google Translate
via the deep-translator library.

Usage:
    from google.translate_service import translate_text

    # Translate a single text
    result = translate_text("Halo dunia", source="id", target="en")

    # Auto-detect source language
    result = translate_text("Hola mundo", source="auto", target="en")
"""

from __future__ import annotations

import logging
import time
from typing import Optional

try:
    from deep_translator import GoogleTranslator
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing dependency 'deep-translator'. Install it with 'pip install deep-translator' and retry."
    ) from exc


logger = logging.getLogger(__name__)

# Default settings
DEFAULT_SOURCE_LANGUAGE = "auto"
DEFAULT_TARGET_LANGUAGE = "en"
DEFAULT_DELAY = 0.1  # Small delay between translations to avoid rate limiting


class TranslationError(RuntimeError):
    """Exception raised when translation fails."""
    pass


def translate_text(
    text: str,
    source: str = DEFAULT_SOURCE_LANGUAGE,
    target: str = DEFAULT_TARGET_LANGUAGE,
    delay: float = DEFAULT_DELAY,
) -> str:
    """Translate text using Google Translate.

    Args:
        text: Text to translate
        source: Source language code (default: "auto" for auto-detect)
                Common codes: "id" (Indonesian), "en" (English), "es" (Spanish), etc.
        target: Target language code (default: "en")
        delay: Delay in seconds after translation (default: 0.1)

    Returns:
        Translated text

    Raises:
        TranslationError: If translation fails

    Examples:
        >>> translate_text("Halo dunia", source="id", target="en")
        'Hello world'

        >>> translate_text("Bonjour le monde", source="auto", target="en")
        'Hello world'
    """
    if not text or not text.strip():
        return text

    try:
        translator = GoogleTranslator(source=source, target=target)
        result = translator.translate(text)

        if delay > 0:
            time.sleep(delay)

        logger.debug(f"Translated: {text[:50]}... -> {result[:50]}...")
        return result

    except Exception as exc:
        logger.warning(f"Translation failed: {exc}")
        logger.warning(f"Original text: {text[:100]}")
        raise TranslationError(f"Failed to translate text: {exc}") from exc


def translate_batch(
    texts: list[str],
    source: str = DEFAULT_SOURCE_LANGUAGE,
    target: str = DEFAULT_TARGET_LANGUAGE,
    delay: float = DEFAULT_DELAY,
    on_error: str = "skip",
) -> list[str]:
    """Translate multiple texts using Google Translate.

    Args:
        texts: List of texts to translate
        source: Source language code (default: "auto")
        target: Target language code (default: "en")
        delay: Delay in seconds between translations (default: 0.1)
        on_error: What to do on error: "skip" (return original), "raise" (raise exception)

    Returns:
        List of translated texts

    Raises:
        TranslationError: If on_error="raise" and translation fails

    Examples:
        >>> translate_batch(["Hola", "Adiós"], source="es", target="en")
        ['Hello', 'Goodbye']
    """
    results = []

    for idx, text in enumerate(texts, 1):
        try:
            translated = translate_text(text, source=source, target=target, delay=delay)
            results.append(translated)
        except TranslationError as exc:
            if on_error == "raise":
                raise
            else:
                logger.warning(f"Skipping failed translation for item {idx}")
                results.append(text)  # Return original on error

    return results


def is_supported_language(lang_code: str) -> bool:
    """Check if a language code is supported by Google Translate.

    Args:
        lang_code: Language code to check (e.g., "en", "id", "es")

    Returns:
        True if supported, False otherwise

    Examples:
        >>> is_supported_language("en")
        True
        >>> is_supported_language("xyz")
        False
    """
    try:
        # Try to get supported languages from GoogleTranslator
        # This is a quick way to validate
        translator = GoogleTranslator(source=lang_code, target="en")
        return True
    except Exception:
        return False


def get_supported_languages() -> dict[str, str]:
    """Get dictionary of all supported language codes and names.

    Returns:
        Dictionary mapping language codes to language names

    Examples:
        >>> langs = get_supported_languages()
        >>> langs["en"]
        'english'
        >>> langs["id"]
        'indonesian'
    """
    try:
        return GoogleTranslator().get_supported_languages(as_dict=True)
    except Exception as exc:
        logger.error(f"Failed to get supported languages: {exc}")
        return {}
