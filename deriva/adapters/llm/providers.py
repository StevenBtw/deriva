"""
LLM Provider abstraction layer.

Defines a Protocol for LLM providers and implementations for:
- Azure OpenAI
- OpenAI
- Anthropic
- Ollama
- Claude Code (via Agent SDK CLI)
"""

from __future__ import annotations

import json
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import requests

from deriva.common.exceptions import ProviderError as ProviderError

# Valid provider names - shared between providers and benchmark models
VALID_PROVIDERS = frozenset({"azure", "openai", "anthropic", "ollama", "claudecode", "mistral"})

__all__ = [
    "VALID_PROVIDERS",
    "ProviderConfig",
    "CompletionResult",
    "ProviderError",
    "LLMProvider",
    "BaseProvider",
    "AzureOpenAIProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "ClaudeCodeProvider",
    "MistralProvider",
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


class MistralProvider(BaseProvider):
    """Mistral AI provider implementation (OpenAI-compatible API)."""

    @property
    def name(self) -> str:
        return "mistral"

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
            raise ProviderError(f"Unexpected Mistral response format: {e}") from e


class ClaudeCodeProvider(BaseProvider):
    """
    Claude Code provider using the Agent SDK CLI.

    This provider uses the `claude` CLI command to send requests,
    leveraging the user's authenticated Claude Code session.
    No API key required - uses OAuth authentication from Claude Code.
    """

    # Model aliases: CLI accepts short names (opus, sonnet, haiku)
    MODEL_ALIASES = {
        "opus": "opus",
        "sonnet": "sonnet",
        "haiku": "haiku",
        "claude-opus-4-5-20251101": "opus",
        "claude-sonnet-4-5-20250929": "sonnet",
        "claude-haiku-4-5-20251001": "haiku",
        "claude-sonnet-4-20250514": "sonnet",
        "claude-3-5-sonnet-20241022": "sonnet",
        "claude-3-5-haiku-20241022": "haiku",
    }

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._cli_verified = False

    def _verify_cli(self) -> None:
        """Verify that the claude CLI is available (once per instance)."""
        if self._cli_verified:
            return
        try:
            # shell=True needed on Windows where claude is a .cmd script
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                shell=(sys.platform == "win32"),
            )
            if result.returncode != 0:
                raise ProviderError(
                    "Claude CLI error. Is Claude Code installed and authenticated?"
                )
            self._cli_verified = True
        except FileNotFoundError as exc:
            raise ProviderError(
                "Claude CLI not found. Install Claude Code: https://claude.ai/claude-code"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("Claude CLI version check timed out") from exc

    def _resolve_model(self, model: str) -> str:
        """Resolve model name to Claude Code CLI model flag."""
        return self.MODEL_ALIASES.get(model.lower(), model)

    def _format_prompt(self, messages: list[dict[str, str]]) -> str:
        """Convert chat messages to a single prompt string for the CLI."""
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"<system>\n{content}\n</system>\n")
            elif role == "assistant":
                parts.append(f"<assistant>\n{content}\n</assistant>\n")
            else:
                parts.append(content)
        return "\n".join(parts)

    def _strip_markdown_code_block(self, content: str) -> str:
        """Strip markdown code block wrappers from content.

        Claude often returns JSON wrapped in ```json ... ``` blocks.
        This strips those wrappers to return clean content.
        """
        import re

        content = content.strip()
        # Match ```json, ```JSON, or just ``` at start, and ``` at end
        pattern = r"^```(?:json|JSON)?\s*\n?(.*?)\n?```$"
        match = re.match(pattern, content, re.DOTALL)
        if match:
            content = match.group(1).strip()

        # Claude sometimes returns Python dict syntax with single quotes
        # Try to fix simple cases for JSON parsing
        if content.startswith("{") and "'" in content:
            try:
                # Try parsing as-is first
                json.loads(content)
            except json.JSONDecodeError:
                # Convert Python dict syntax to JSON (single → double quotes)
                # This handles simple cases like {'key': 'value'}
                import ast

                try:
                    # ast.literal_eval safely parses Python literals
                    parsed = ast.literal_eval(content)
                    if isinstance(parsed, dict):
                        content = json.dumps(parsed)
                except (ValueError, SyntaxError):
                    pass  # Keep original if parsing fails

        return content

    @property
    def name(self) -> str:
        return "claudecode"

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        self._verify_cli()

        prompt = self._format_prompt(messages)
        if json_mode:
            prompt += "\n\nRespond with valid JSON only."

        resolved_model = self._resolve_model(self.config.model)

        cmd = [
            "claude",
            "-p",
            prompt,
            "--model",
            resolved_model,
            "--output-format",
            "json",
        ]
        if max_tokens:
            cmd.extend(["--max-tokens", str(max_tokens)])

        try:
            # shell=True needed on Windows where claude is a .cmd script
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                check=False,
                shell=(sys.platform == "win32"),
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                raise ProviderError(f"Claude CLI error: {error_msg}")

            # Parse JSON output
            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError:
                return CompletionResult(
                    content=result.stdout.strip(),
                    finish_reason="stop",
                )

            # Extract content from JSON output
            content = ""
            if isinstance(output, dict):
                content = output.get("result", output.get("content", str(output)))
                if isinstance(content, dict):
                    content = content.get("text", json.dumps(content))
            elif isinstance(output, str):
                content = output
            else:
                content = json.dumps(output)

            # Strip markdown code blocks if present (Claude often wraps JSON in ```json ... ```)
            content = self._strip_markdown_code_block(content)

            usage = None
            if isinstance(output, dict) and (
                output.get("cost_usd") or output.get("duration_ms")
            ):
                usage = {
                    "cost_usd": output.get("cost_usd"),
                    "duration_ms": output.get("duration_ms"),
                }

            return CompletionResult(
                content=content,
                usage=usage,
                finish_reason="stop",
                raw_response=output if isinstance(output, dict) else None,
            )

        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"Claude CLI timed out after {self.config.timeout}s"
            ) from exc
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Claude Code request failed: {e}") from e


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
        "claudecode": ClaudeCodeProvider,
        "mistral": MistralProvider,
    }

    provider_class = providers.get(provider_name.lower())
    if not provider_class:
        available = ", ".join(providers.keys())
        raise ValueError(f"Unknown provider: {provider_name}. Available: {available}")

    return provider_class(config)
