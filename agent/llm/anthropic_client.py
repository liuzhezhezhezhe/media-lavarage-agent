import anthropic
from agent.llm.base import LLMClient, LLMResponse


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system: str, user: str, max_tokens: int = 4096) -> LLMResponse:
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        content = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        finish_reason = msg.stop_reason or ""
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)
        return LLMResponse(
            content=content,
            tokens_used=tokens,
            model=self._model,
            finish_reason=finish_reason,
            is_truncated=self._is_truncated_finish_reason(finish_reason),
        )

    async def chat(self, system: str, messages: list[dict], max_tokens: int = 1024) -> LLMResponse:
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        content = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        finish_reason = msg.stop_reason or ""
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)
        return LLMResponse(
            content=content,
            tokens_used=tokens,
            model=self._model,
            finish_reason=finish_reason,
            is_truncated=self._is_truncated_finish_reason(finish_reason),
        )
