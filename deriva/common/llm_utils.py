"""LLM response utilities for Deriva.

Provides consistent handling of LLM response objects across the pipeline.
"""

from __future__ import annotations

from typing import Any

from .types import LLMDetails

__all__ = ["create_empty_llm_details", "extract_llm_details"]


def create_empty_llm_details() -> LLMDetails:
    """
    Create an empty LLM details dictionary for initialization.

    Returns:
        Dictionary with default values for LLM tracking:
            - prompt: Empty string
            - response: Empty string
            - tokens_in: 0
            - tokens_out: 0
            - cache_used: False
    """
    return {
        "prompt": "",
        "response": "",
        "tokens_in": 0,
        "tokens_out": 0,
        "cache_used": False,
    }


def extract_llm_details(response: Any) -> LLMDetails:
    """
    Extract LLM details from a response object.

    Works with LLMResponse objects from deriva.adapters.llm that have:
    - content: The response text
    - usage: Dict with prompt_tokens and completion_tokens
    - response_type: ResponseType enum indicating if cached

    Args:
        response: LLM response object (typically LLMResponse from deriva.adapters.llm)

    Returns:
        Dictionary with extracted details:
            - prompt: Empty (not available from response)
            - response: The response content
            - tokens_in: Input token count
            - tokens_out: Output token count
            - cache_used: Whether response was from cache
    """
    details = create_empty_llm_details()

    if hasattr(response, "content"):
        details["response"] = response.content

    if hasattr(response, "usage") and response.usage:
        details["tokens_in"] = response.usage.get("prompt_tokens", 0)
        details["tokens_out"] = response.usage.get("completion_tokens", 0)

    if hasattr(response, "response_type"):
        details["cache_used"] = str(response.response_type) == "ResponseType.CACHED"

    return details
