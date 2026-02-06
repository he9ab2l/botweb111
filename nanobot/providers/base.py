"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    thinking: str | None = None
    
    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response.

    Exactly one of the content fields will be non-None for a given chunk.
    """
    delta: str | None = None          # text content delta
    thinking_delta: str | None = None  # thinking/reasoning delta
    tool_calls_delta: list[dict[str, Any]] | None = None  # incremental tool call
    finish_reason: str | None = None   # set on last chunk
    usage: dict[str, int] | None = None  # set on last chunk


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Implementations should handle the specifics of each provider's API
    while maintaining a consistent interface.
    """
    
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base
    
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request (non-streaming).
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions.
            model: Model identifier (provider-specific).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        pass

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        """
        Send a streaming chat completion request.

        Default implementation falls back to non-streaming chat()
        and yields a single chunk with the full response.

        Yields:
            StreamChunk instances with incremental content.
        """
        response = await self.chat(messages, tools, model, max_tokens, temperature)
        if response.content:
            yield StreamChunk(delta=response.content)
        if response.has_tool_calls:
            for tc in response.tool_calls:
                yield StreamChunk(
                    tool_calls_delta=[{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }]
                )
        yield StreamChunk(
            finish_reason=response.finish_reason,
            usage=response.usage or None,
        )
    
    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass
