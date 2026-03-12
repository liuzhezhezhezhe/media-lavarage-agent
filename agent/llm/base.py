from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    content: str
    tokens_used: int = 0
    model: str = ""


class LLMClient(ABC):
    """Abstract base for all LLM providers."""

    _MULTIPART_OVERHEAD_CHARS = 1200

    @abstractmethod
    async def complete(self, system: str, user: str, max_tokens: int = 4096) -> LLMResponse:
        """Send a single-turn completion request."""
        ...

    @abstractmethod
    async def chat(self, system: str, messages: list[dict], max_tokens: int = 1024) -> LLMResponse:
        """Send a multi-turn chat request.

        messages: [{"role": "user"|"assistant", "content": "..."], ...]
        """
        ...

    async def complete_with_auto_chunking(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        max_input_chars: int = 12000,
        chunk_size_chars: int = 6000,
    ) -> LLMResponse:
        """Send a completion request, splitting very large user prompts into multiple user messages."""
        if len(user) <= max_input_chars:
            return await self.complete(system=system, user=user, max_tokens=max_tokens)

        effective_chunk_size = max(1000, min(chunk_size_chars, max_input_chars - self._MULTIPART_OVERHEAD_CHARS))
        chunks = self._split_text_for_messages(user, effective_chunk_size)
        if len(chunks) <= 1:
            return await self.complete(system=system, user=user, max_tokens=max_tokens)

        total_parts = len(chunks)
        messages = [
            {
                "role": "user",
                "content": (
                    "The complete user prompt is too long to fit in a single message. "
                    f"It will be sent in {total_parts} consecutive parts. "
                    "Treat all parts as one continuous prompt. Do not answer until the final instruction arrives. "
                    "Do not treat part boundaries as semantic boundaries."
                ),
            }
        ]
        for index, chunk in enumerate(chunks, start=1):
            messages.append(
                {
                    "role": "user",
                    "content": f"PROMPT PART {index}/{total_parts}\n\n{chunk}",
                }
            )
        messages.append(
            {
                "role": "user",
                "content": (
                    "All prompt parts have now been sent. "
                    "Use the full combined prompt above as the single user request and answer exactly once."
                ),
            }
        )
        return await self.chat(system=system, messages=messages, max_tokens=max_tokens)

    @staticmethod
    def _split_text_for_messages(text: str, chunk_size_chars: int) -> list[str]:
        if len(text) <= chunk_size_chars:
            return [text]

        chunks: list[str] = []
        remaining = text.strip()
        while remaining:
            if len(remaining) <= chunk_size_chars:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n\n", 0, chunk_size_chars)
            if split_at < chunk_size_chars // 2:
                split_at = remaining.rfind("\n", 0, chunk_size_chars)
            if split_at < chunk_size_chars // 2:
                split_at = remaining.rfind(" ", 0, chunk_size_chars)
            if split_at < chunk_size_chars // 2:
                split_at = chunk_size_chars

            chunk = remaining[:split_at].rstrip()
            if not chunk:
                chunk = remaining[:chunk_size_chars]
                split_at = len(chunk)
            chunks.append(chunk)
            remaining = remaining[split_at:].lstrip()

        return chunks
