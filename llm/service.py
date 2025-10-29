"""
Centralized LLM Service for ManualBook system.

Supports multiple API providers:
- OpenAI-compatible APIs (LM Studio, Ollama, vLLM, etc.)
- Cloudflare AI Workers

All embedding and text generation operations should use this service.

Usage:
    from llm.service import get_embeddings, get_completion, get_gloss

    # Get embeddings
    embeddings = get_embeddings(["text1", "text2"])

    # Get LLM completion
    response = get_completion(
        prompt="What is AI?",
        system_prompt="You are a helpful assistant",
        temperature=0.7
    )

    # Get one-line gloss/summary
    gloss = get_gloss("Long document text here...")
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration from environment variables
# ============================================================================

API_PROVIDER = os.environ.get("API_PROVIDER", "openai").lower()

# Cloudflare AI Workers configuration
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "633ad1c872777d27fb15d076ff25e1f6")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "hzrMSv-yoj2lrvSgr7nnyWvX_aaGSYeivdzMIBxi")
CLOUDFLARE_EMBEDDING_MODEL = os.environ.get("CLOUDFLARE_EMBEDDING_MODEL", "@cf/baai/bge-base-en-v1.5")
CLOUDFLARE_LLM_MODEL = os.environ.get("CLOUDFLARE_LLM_MODEL", "@cf/meta/llama-3.1-8b-instruct")

# OpenAI-compatible API configuration (LM Studio, Ollama, etc.)
OPENAI_API_BASE = os.environ.get("EMBEDDING_API_BASE", "https://api.cloudflare.com/client/v4/accounts/633ad1c872777d27fb15d076ff25e1f6/ai/v1")
OPENAI_API_KEY = os.environ.get("EMBEDDING_API_KEY", "hzrMSv-yoj2lrvSgr7nnyWvX_aaGSYeivdzMIBxi")
OPENAI_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")
OPENAI_LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5-32b-instruct-mlx")

# Retry configuration
RETRY_LIMIT = int(os.environ.get("LLM_RETRY_LIMIT", "3"))
RETRY_BACKOFF = float(os.environ.get("LLM_RETRY_BACKOFF", "2.0"))


# ============================================================================
# Exceptions
# ============================================================================


class LLMServiceError(RuntimeError):
    """Base exception for LLM service errors."""
    pass


# ============================================================================
# Helper functions
# ============================================================================


def _cloudflare_headers() -> Dict[str, str]:
    """Get headers for Cloudflare API requests."""
    if not CLOUDFLARE_API_TOKEN:
        raise LLMServiceError(
            "CLOUDFLARE_API_TOKEN environment variable is required when using Cloudflare provider"
        )
    return {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _openai_headers() -> Dict[str, str]:
    """Get headers for OpenAI-compatible API requests."""
    headers = {"Content-Type": "application/json"}
    if OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
    return headers


def _cloudflare_url(model: str) -> str:
    """Construct Cloudflare AI Workers URL."""
    if not CLOUDFLARE_ACCOUNT_ID:
        raise LLMServiceError(
            "CLOUDFLARE_ACCOUNT_ID environment variable is required when using Cloudflare provider"
        )
    return f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"


# ============================================================================
# Embedding Functions
# ============================================================================


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Get embeddings for a list of texts.

    Args:
        texts: List of strings to embed

    Returns:
        List of embedding vectors (one per input text)

    Raises:
        LLMServiceError: If the request fails after retries
    """
    if not texts:
        return []

    logger.debug(f"Getting embeddings for {len(texts)} texts using {API_PROVIDER} provider")

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            if API_PROVIDER == "cloudflare":
                embeddings = _get_embeddings_cloudflare(texts)
            else:
                embeddings = _get_embeddings_openai(texts)

            logger.debug(f"Successfully got {len(embeddings)} embeddings (attempt {attempt})")
            return embeddings

        except requests.RequestException as exc:
            logger.warning(f"Embedding attempt {attempt} failed: {exc}")
            if attempt == RETRY_LIMIT:
                raise LLMServiceError(
                    f"Failed to get embeddings after {RETRY_LIMIT} attempts: {exc}"
                ) from exc
            time.sleep(RETRY_BACKOFF * attempt)

    raise LLMServiceError("Unexpected error in get_embeddings")


def _get_embeddings_openai(texts: List[str]) -> List[List[float]]:
    """Get embeddings using OpenAI-compatible API."""
    url = OPENAI_API_BASE.rstrip("/") + "/embeddings"
    payload = {"model": OPENAI_EMBEDDING_MODEL, "input": texts}

    response = requests.post(url, headers=_openai_headers(), json=payload, timeout=120)

    # Fallback for servers without /embeddings endpoint
    if response.status_code in {404, 405, 501}:
        logger.debug("Embeddings endpoint not available, falling back to chat completion")
        return [_get_embedding_via_chat_openai(text) for text in texts]

    if response.status_code >= 400:
        raise LLMServiceError(
            f"OpenAI embeddings error {response.status_code}: {response.text}"
        )

    data = response.json()
    items = data.get("data", [])

    if len(items) != len(texts):
        raise LLMServiceError(f"Expected {len(texts)} embeddings, got {len(items)}")

    return [item["embedding"] for item in items]


def _get_embedding_via_chat_openai(text: str) -> List[float]:
    """Fallback: Get embedding via chat completion."""
    url = OPENAI_API_BASE.rstrip("/") + "/chat/completions"
    payload = {
        "model": OPENAI_EMBEDDING_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an embedding service. Respond with a JSON object containing "
                    "a single key 'embedding', whose value is an array of floating point "
                    "numbers representing the semantic embedding of the given text. "
                    "Do not include any other fields."
                ),
            },
            {"role": "user", "content": text},
        ],
    }

    response = requests.post(url, headers=_openai_headers(), json=payload, timeout=180)

    if response.status_code >= 400:
        raise LLMServiceError(
            f"OpenAI chat embedding error {response.status_code}: {response.text}"
        )

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return [float(x) for x in parsed["embedding"]]


def _get_embeddings_cloudflare(texts: List[str]) -> List[List[float]]:
    """Get embeddings using Cloudflare AI Workers."""
    url = _cloudflare_url(CLOUDFLARE_EMBEDDING_MODEL)
    embeddings = []

    for text in texts:
        payload = {"text": [text]}

        response = requests.post(url, headers=_cloudflare_headers(), json=payload, timeout=120)

        if response.status_code >= 400:
            raise LLMServiceError(
                f"Cloudflare embeddings error {response.status_code}: {response.text}"
            )

        data = response.json()

        # Cloudflare response: {"result": {"shape": [1, dim], "data": [[...]]}}
        if "result" not in data or "data" not in data["result"]:
            raise LLMServiceError(f"Unexpected Cloudflare response format: {data}")

        embedding_data = data["result"]["data"]
        if not embedding_data or not isinstance(embedding_data[0], list):
            raise LLMServiceError(f"Invalid embedding data: {embedding_data}")

        embeddings.append(embedding_data[0])

    return embeddings


# ============================================================================
# Text Generation Functions
# ============================================================================


def get_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    """
    Get a text completion from the LLM.

    Args:
        prompt: User prompt/question
        system_prompt: Optional system prompt to guide the model
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
        max_tokens: Maximum tokens to generate

    Returns:
        Generated text response

    Raises:
        LLMServiceError: If the request fails after retries
    """
    logger.debug(f"Getting completion using {API_PROVIDER} provider (temp={temperature}, max_tokens={max_tokens})")

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            if API_PROVIDER == "cloudflare":
                result = _get_completion_cloudflare(prompt, system_prompt, temperature, max_tokens)
            else:
                result = _get_completion_openai(prompt, system_prompt, temperature, max_tokens)

            logger.debug(f"Successfully got completion (attempt {attempt}, length={len(result)})")
            return result

        except requests.RequestException as exc:
            logger.warning(f"Completion attempt {attempt} failed: {exc}")
            if attempt == RETRY_LIMIT:
                raise LLMServiceError(
                    f"Failed to get completion after {RETRY_LIMIT} attempts: {exc}"
                ) from exc
            time.sleep(RETRY_BACKOFF * attempt)

    raise LLMServiceError("Unexpected error in get_completion")


def _get_completion_openai(
    prompt: str,
    system_prompt: Optional[str],
    temperature: float,
    max_tokens: int,
) -> str:
    """Get completion using OpenAI-compatible API."""
    url = OPENAI_API_BASE.rstrip("/") + "/chat/completions"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": OPENAI_LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    response = requests.post(url, headers=_openai_headers(), json=payload, timeout=180)

    if response.status_code >= 400:
        raise LLMServiceError(
            f"OpenAI completion error {response.status_code}: {response.text}"
        )

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _get_completion_cloudflare(
    prompt: str,
    system_prompt: Optional[str],
    temperature: float,
    max_tokens: int,
) -> str:
    """Get completion using Cloudflare AI Workers."""
    url = _cloudflare_url(CLOUDFLARE_LLM_MODEL)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    response = requests.post(url, headers=_cloudflare_headers(), json=payload, timeout=180)

    if response.status_code >= 400:
        raise LLMServiceError(
            f"Cloudflare completion error {response.status_code}: {response.text}"
        )

    data = response.json()

    # Cloudflare response: {"result": {"response": "..."}}
    if "result" not in data or "response" not in data["result"]:
        raise LLMServiceError(f"Unexpected Cloudflare response format: {data}")

    return data["result"]["response"].strip()


# ============================================================================
# Specialized Functions
# ============================================================================


def get_gloss(text: str) -> str:
    """
    Generate a one-line summary/gloss of the given text.

    Args:
        text: The text to summarize

    Returns:
        A concise one-sentence summary (under 25 words)

    Raises:
        LLMServiceError: If the request fails
    """
    system_prompt = (
        "You condense documentation passages into a single, fluent English sentence. "
        "Keep it under 25 words and describe the key idea plainly."
    )

    return get_completion(
        prompt=text,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=120,
    )


def translate_text(
    text: str,
    target_language: str = "English",
    preserve_markdown: bool = True,
) -> str:
    """
    Translate text to the target language.

    Args:
        text: The text to translate
        target_language: Target language (default: "English")
        preserve_markdown: Whether to preserve Markdown formatting

    Returns:
        Translated text

    Raises:
        LLMServiceError: If the request fails
    """
    if preserve_markdown:
        system_prompt = (
            f"You are a translation assistant. Translate the user's Markdown "
            f"content into clear and natural {target_language} while preserving Markdown "
            f"structure, headings, tables, lists, and inline formatting. "
            f"Do not add commentary or explanation; return only the translated Markdown."
        )
    else:
        system_prompt = (
            f"You are a translation assistant. Translate the user's text into "
            f"clear and natural {target_language}. Return only the translation, "
            f"without commentary or explanation."
        )

    return get_completion(
        prompt=text,
        system_prompt=system_prompt,
        temperature=0.0,
        max_tokens=800,
    )


def generate_answer(
    query: str,
    context: str,
    sources: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Generate an answer to a query using provided context.

    Args:
        query: The user's question
        context: Relevant context/documentation
        sources: Optional list of source metadata

    Returns:
        Generated answer

    Raises:
        LLMServiceError: If the request fails
    """
    system_prompt = (
        "You are a helpful assistant that produces concise, factual answers. "
        "Use the supplied context to answer the user's query. Cite relevant sections "
        "by referencing their titles when useful. If the context is insufficient, say so."
    )

    source_block = ""
    if sources:
        source_lines = []
        for src in sources:
            title = src.get("title") or "Untitled"
            origin = src.get("source_file") or src.get("source_kind") or ""
            source_lines.append(f"- {title} ({origin})")
        source_block = f"\n\nSources:\n" + "\n".join(source_lines)

    full_prompt = (
        f"Context:\n{context}\n{source_block}\n\n"
        f"User question: {query}\n\n"
        f"Respond with a helpful answer."
    )

    return get_completion(
        prompt=full_prompt,
        system_prompt=system_prompt,
        temperature=0.2,
        max_tokens=512,
    )


# ============================================================================
# Utility Functions
# ============================================================================


def get_provider_info() -> Dict[str, str]:
    """Get information about the current API provider configuration."""
    info = {"provider": API_PROVIDER}

    if API_PROVIDER == "cloudflare":
        info.update({
            "account_id": (CLOUDFLARE_ACCOUNT_ID[:8] + "..." if CLOUDFLARE_ACCOUNT_ID else "NOT SET"),
            "has_token": "Yes" if CLOUDFLARE_API_TOKEN else "No",
            "embedding_model": CLOUDFLARE_EMBEDDING_MODEL,
            "llm_model": CLOUDFLARE_LLM_MODEL,
        })
    else:
        info.update({
            "api_base": OPENAI_API_BASE,
            "has_key": "Yes" if OPENAI_API_KEY else "No",
            "embedding_model": OPENAI_EMBEDDING_MODEL,
            "llm_model": OPENAI_LLM_MODEL,
        })

    return info


def test_connection() -> bool:
    """
    Test the connection to the LLM service.

    Returns:
        True if connection is successful, False otherwise
    """
    try:
        logger.info("Testing LLM service connection...")
        embeddings = get_embeddings(["test"])
        logger.info(f"✓ Embeddings working (dimension: {len(embeddings[0])})")

        response = get_completion("Say 'OK'", temperature=0)
        logger.info(f"✓ Completions working (response: {response[:50]}...)")

        return True
    except Exception as exc:
        logger.error(f"✗ Connection test failed: {exc}")
        return False


# ============================================================================
# CLI Test Interface
# ============================================================================


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("="*70)
    print("LLM Service Configuration")
    print("="*70)

    info = get_provider_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

    print("\n" + "="*70)
    print("Testing Connection")
    print("="*70)

    success = test_connection()

    if success:
        print("\n✓ All tests passed!")
    else:
        print("\n✗ Tests failed. Check configuration.")
        exit(1)
