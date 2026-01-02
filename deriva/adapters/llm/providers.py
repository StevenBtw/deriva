"""
LLM Provider abstraction layer.

Defines a Protocol for LLM providers and implementations for:
- Azure OpenAI
- OpenAI
- Anthropic
- Ollama
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import requests

from deriva.common.exceptions import ProviderError as ProviderError

__all__ = [
    "ProviderConfig",
    "CompletionResult",
    "ProviderError",
    "LLMProvider",
    "BaseProvider",
    "AzureOpenAIProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "create_provider",
]


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    api_url: str
    api_key: str | None
    model: str
    timeout: int = 60


@dataclass
class CompletionResult:
    """Raw result from a provider completion call."""

    content: str
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
    raw_response: dict[str, Any] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol defining the interface for LLM providers."""

    @property
    def name(self) -> str:
        """Provider name identifier."""
        ...

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        """
        Send a completion request to the provider.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            json_mode: Whether to request JSON output

        Returns:
            CompletionResult with content and metadata

        Raises:
            ProviderError: If the API call fails
        """
        ...


class BaseProvider(ABC):
    """Base class for LLM providers with common functionality."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name identifier."""
        ...

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        """Send a completion request."""
        ...

    def _make_request(
        self, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        """Make HTTP request to provider API."""
        try:
            response = requests.post(
                self.config.api_url,
                headers=headers,
                json=body,
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            raise ProviderError(f"{self.name} API request timed out") from e
        except requests.exceptions.RequestException as e:
            raise ProviderError(f"{self.name} API request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise ProviderError(f"{self.name} returned invalid JSON") from e


class AzureOpenAIProvider(BaseProvider):
    """Azure OpenAI provider implementation."""

    @property
    def name(self) -> str:
        return "azure"

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        headers = {
            "Content-Type": "application/json",
            "api-key": self.config.api_key or "",
        }

        body: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            body["max_tokens"] = max_tokens

        if json_mode:
            body["response_format"] = {"type": "json_object"}

        response = self._make_request(headers, body)

        try:
            content = response["choices"][0]["message"]["content"]
            usage = response.get("usage")
            finish_reason = response["choices"][0].get("finish_reason")
            return CompletionResult(
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                raw_response=response,
            )
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected Azure response format: {e}") from e


class OpenAIProvider(BaseProvider):
    """OpenAI provider implementation."""

    @property
    def name(self) -> str:
        return "openai"

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            body["max_tokens"] = max_tokens

        if json_mode:
            body["response_format"] = {"type": "json_object"}

        response = self._make_request(headers, body)

        try:
            content = response["choices"][0]["message"]["content"]
            usage = response.get("usage")
            finish_reason = response["choices"][0].get("finish_reason")
            return CompletionResult(
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                raw_response=response,
            )
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected OpenAI response format: {e}") from e


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider implementation."""

    @property
    def name(self) -> str:
        return "anthropic"

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
        }

        # Anthropic uses a different message format - extract system message
        system_message = None
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                user_messages.append(msg)

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": user_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,  # Anthropic requires max_tokens
        }

        if system_message:
            body["system"] = system_message

        response = self._make_request(headers, body)

        try:
            # Anthropic returns content as a list of content blocks
            content_blocks = response.get("content", [])
            content = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    content += block.get("text", "")

            usage = response.get("usage")
            # Map Anthropic usage format to standard format
            if usage:
                usage = {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0)
                    + usage.get("output_tokens", 0),
                }

            finish_reason = response.get("stop_reason")
            return CompletionResult(
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                raw_response=response,
            )
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected Anthropic response format: {e}") from e


class OllamaProvider(BaseProvider):
    """Ollama local LLM provider implementation."""

    @property
    def name(self) -> str:
        return "ollama"

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        headers = {
            "Content-Type": "application/json",
        }

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        if max_tokens:
            body["options"]["num_predict"] = max_tokens

        if json_mode:
            body["format"] = "json"

        response = self._make_request(headers, body)

        try:
            content = response["message"]["content"]
            # Ollama provides different usage metrics
            usage = None
            if "eval_count" in response or "prompt_eval_count" in response:
                usage = {
                    "prompt_tokens": response.get("prompt_eval_count", 0),
                    "completion_tokens": response.get("eval_count", 0),
                    "total_tokens": response.get("prompt_eval_count", 0)
                    + response.get("eval_count", 0),
                }

            finish_reason = "stop" if response.get("done") else None
            return CompletionResult(
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                raw_response=response,
            )
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected Ollama response format: {e}") from e


def create_provider(provider_name: str, config: ProviderConfig) -> LLMProvider:
    """
    Factory function to create a provider instance.

    Args:
        provider_name: Name of the provider (azure, openai, anthropic, ollama)
        config: Provider configuration

    Returns:
        LLMProvider instance

    Raises:
        ValueError: If provider name is unknown
    """
    providers: dict[str, type[BaseProvider]] = {
        "azure": AzureOpenAIProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
    }

    provider_class = providers.get(provider_name.lower())
    if not provider_class:
        available = ", ".join(providers.keys())
        raise ValueError(f"Unknown provider: {provider_name}. Available: {available}")

    return provider_class(config)
