"""LiteLLM provider implementation for multi-provider support."""

import json
import os
from typing import Any, AsyncIterator

import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk, ToolCallRequest


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.
    
    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5"
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        
        # Detect OpenRouter by api_key prefix or explicit api_base
        self.is_openrouter = (
            (api_key and api_key.startswith("sk-or-")) or
            (api_base and "openrouter" in api_base)
        )
        
        # Track if using custom endpoint (vLLM, etc.)
        self.is_vllm = bool(api_base) and not self.is_openrouter
        
        # Configure LiteLLM based on provider
        if api_key:
            if self.is_openrouter:
                os.environ["OPENROUTER_API_KEY"] = api_key
            elif self.is_vllm:
                os.environ["OPENAI_API_KEY"] = api_key
            elif "deepseek" in default_model:
                os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
            elif "anthropic" in default_model:
                os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            elif "openai" in default_model or "gpt" in default_model:
                os.environ.setdefault("OPENAI_API_KEY", api_key)
            elif "gemini" in default_model.lower():
                os.environ.setdefault("GEMINI_API_KEY", api_key)
            elif "zhipu" in default_model or "glm" in default_model or "zai" in default_model:
                os.environ.setdefault("ZHIPUAI_API_KEY", api_key)
                os.environ.setdefault("ZAI_API_KEY", api_key)
            elif "groq" in default_model:
                os.environ.setdefault("GROQ_API_KEY", api_key)
            elif "moonshot" in default_model or "kimi" in default_model:
                os.environ.setdefault("MOONSHOT_API_KEY", api_key)
                os.environ.setdefault("MOONSHOT_API_BASE", api_base or "https://api.moonshot.cn/v1")
        
        if api_base:
            litellm.api_base = api_base
        
        litellm.suppress_debug_info = True

    def _resolve_model(self, model: str | None) -> str:
        """Resolve model name with provider-specific prefixes."""
        model = model or self.default_model

        if self.is_openrouter and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"

        if ("glm" in model.lower() or "zhipu" in model.lower()) and not (
            model.startswith("zhipu/")
            or model.startswith("zai/")
            or model.startswith("openrouter/")
        ):
            model = f"zai/{model}"

        if ("moonshot" in model.lower() or "kimi" in model.lower()) and not (
            model.startswith("moonshot/") or model.startswith("openrouter/")
        ):
            model = f"moonshot/{model}"

        if "gemini" in model.lower() and not model.startswith("gemini/"):
            model = f"gemini/{model}"

        if self.is_vllm:
            model = f"hosted_vllm/{model}"

        return model

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        stream: bool = False,
    ) -> dict[str, Any]:
        model = self._resolve_model(model)

        if "kimi-k2.5" in model.lower():
            temperature = 1.0

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

        if self.api_base:
            kwargs["api_base"] = self.api_base

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return kwargs

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a non-streaming chat completion request via LiteLLM."""
        kwargs = self._build_kwargs(messages, tools, model, max_tokens, temperature, stream=False)
        
        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        """
        Send a streaming chat completion request via LiteLLM.

        Yields StreamChunk instances as they arrive from the model.
        Falls back to non-streaming if the provider doesn't support it.
        """
        kwargs = self._build_kwargs(messages, tools, model, max_tokens, temperature, stream=True)

        try:
            response = await acompletion(**kwargs)

            # Accumulate tool call fragments across chunks
            tc_buffers: dict[int, dict[str, Any]] = {}  # index -> {id, name, args_str}
            usage_data: dict[str, int] | None = None

            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                finish = chunk.choices[0].finish_reason if chunk.choices else None

                if hasattr(chunk, "usage") and chunk.usage:
                    usage_data = {
                        "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                        "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                    }

                if delta is None:
                    if finish:
                        yield StreamChunk(finish_reason=finish, usage=usage_data)
                    continue

                # Text content delta
                text_delta = getattr(delta, "content", None)
                if text_delta:
                    yield StreamChunk(delta=text_delta)

                # Thinking/reasoning delta (Claude extended thinking, etc.)
                thinking = getattr(delta, "reasoning_content", None) or getattr(delta, "thinking", None)
                if thinking:
                    yield StreamChunk(thinking_delta=thinking)

                # Tool call deltas (accumulated until complete)
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index if hasattr(tc_delta, "index") else 0
                        if idx not in tc_buffers:
                            tc_buffers[idx] = {
                                "id": "",
                                "name": "",
                                "args_str": "",
                            }
                        buf = tc_buffers[idx]
                        if hasattr(tc_delta, "id") and tc_delta.id:
                            buf["id"] = tc_delta.id
                        if hasattr(tc_delta, "function"):
                            fn = tc_delta.function
                            if hasattr(fn, "name") and fn.name:
                                buf["name"] = fn.name
                            if hasattr(fn, "arguments") and fn.arguments:
                                buf["args_str"] += fn.arguments

                if finish:
                    # Emit accumulated tool calls
                    if tc_buffers:
                        calls = []
                        for _idx, buf in sorted(tc_buffers.items()):
                            try:
                                args = json.loads(buf["args_str"]) if buf["args_str"] else {}
                            except json.JSONDecodeError:
                                args = {"raw": buf["args_str"]}
                            calls.append({
                                "id": buf["id"],
                                "type": "function",
                                "function": {"name": buf["name"], "arguments": args},
                            })
                        yield StreamChunk(tool_calls_delta=calls)

                    yield StreamChunk(finish_reason=finish, usage=usage_data)

        except Exception as e:
            # Fallback: non-streaming
            from loguru import logger
            logger.warning(f"Streaming failed, falling back to non-streaming: {e}")
            async for chunk in super().chat_stream(messages, tools, model, max_tokens, temperature):
                yield chunk
    
    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message
        
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))
        
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        thinking = None
        if hasattr(message, "reasoning_content"):
            thinking = message.reasoning_content
        
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            thinking=thinking,
        )
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
