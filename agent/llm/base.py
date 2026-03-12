from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    tokens_used: int = 0
    model: str = ""
    finish_reason: str = ""
    is_truncated: bool = False


class LLMClient(ABC):
    """Abstract base for all LLM providers."""

    _MULTIPART_OVERHEAD_CHARS = 1200
    _DEFAULT_MAX_CONTINUATIONS = 8
    _TRUNCATED_FINISH_REASONS = {"length", "max_tokens", "model_context_window_exceeded"}

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
        max_total_input_chars: int = 48000,
    ) -> LLMResponse:
        """Send a completion request, splitting very large user prompts into multiple user messages."""
        if len(user) <= max_input_chars:
            return await self.complete(system=system, user=user, max_tokens=max_tokens)

        messages = self._build_multipart_prompt_messages(
            user,
            max_input_chars=max_input_chars,
            chunk_size_chars=chunk_size_chars,
            max_total_input_chars=max_total_input_chars,
        )
        return await self._continue_chat_response(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            max_continuations=self._DEFAULT_MAX_CONTINUATIONS,
        )

    async def complete_safe(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        max_input_chars: int = 12000,
        chunk_size_chars: int = 6000,
        max_total_input_chars: int = 48000,
        max_continuations: int = _DEFAULT_MAX_CONTINUATIONS,
    ) -> LLMResponse:
        """Send a completion request with multipart input and continuation safeguards."""
        if len(user) <= max_input_chars:
            response = await self.complete(system=system, user=user, max_tokens=max_tokens)
            if not response.is_truncated:
                return response
            return await self._continue_chat_response(
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                max_continuations=max_continuations,
                initial_response=response,
            )

        messages = self._build_multipart_prompt_messages(
            user,
            max_input_chars=max_input_chars,
            chunk_size_chars=chunk_size_chars,
            max_total_input_chars=max_total_input_chars,
        )
        return await self._continue_chat_response(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            max_continuations=max_continuations,
        )

    async def chat_safe(
        self,
        system: str,
        messages: list[dict],
        *,
        max_tokens: int = 1024,
        max_input_chars: int = 12000,
        chunk_size_chars: int = 6000,
        max_total_input_chars: int = 48000,
        max_continuations: int = _DEFAULT_MAX_CONTINUATIONS,
    ) -> LLMResponse:
        """Send a chat request with multipart input and continuation safeguards."""
        request_messages = self._build_safe_chat_messages(
            messages,
            max_input_chars=max_input_chars,
            chunk_size_chars=chunk_size_chars,
            max_total_input_chars=max_total_input_chars,
        )
        return await self._continue_chat_response(
            system=system,
            messages=request_messages,
            max_tokens=max_tokens,
            max_continuations=max_continuations,
        )

    async def _continue_chat_response(
        self,
        *,
        system: str,
        messages: list[dict],
        max_tokens: int,
        max_continuations: int,
        initial_response: LLMResponse | None = None,
    ) -> LLMResponse:
        working_messages = [dict(item) for item in messages]
        aggregated_content = ""
        tokens_used = 0
        model = ""
        finish_reason = ""
        response = initial_response

        if response is None:
            response = await self.chat(system=system, messages=working_messages, max_tokens=max_tokens)

        aggregated_content = response.content or ""
        tokens_used = response.tokens_used
        model = response.model
        finish_reason = response.finish_reason

        for _ in range(max_continuations):
            if not response.is_truncated:
                break

            continuation_segment = response.content or ""
            working_messages.extend(
                [
                    {"role": "assistant", "content": continuation_segment},
                    {"role": "user", "content": self._continuation_prompt()},
                ]
            )
            response = await self.chat(system=system, messages=working_messages, max_tokens=max_tokens)
            aggregated_content = self._merge_text_segments(aggregated_content, response.content or "")
            tokens_used += response.tokens_used
            if not model:
                model = response.model
            finish_reason = response.finish_reason

        return LLMResponse(
            content=aggregated_content,
            tokens_used=tokens_used,
            model=model,
            finish_reason=finish_reason,
            is_truncated=response.is_truncated,
        )

    def _build_multipart_prompt_messages(
        self,
        user: str,
        *,
        max_input_chars: int,
        chunk_size_chars: int,
        max_total_input_chars: int,
    ) -> list[dict]:
        stripped_user = user.strip()
        if len(stripped_user) > max_total_input_chars:
            raise ValueError(
                "LLM input exceeds the maximum supported size even before multipart chunking."
            )

        effective_chunk_size = max(1000, min(chunk_size_chars, max_input_chars - self._MULTIPART_OVERHEAD_CHARS))
        chunks = self._split_text_for_messages(user, effective_chunk_size)
        if len(chunks) <= 1:
            return [{"role": "user", "content": user}]

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
        return messages

    def _build_safe_chat_messages(
        self,
        messages: list[dict],
        *,
        max_input_chars: int,
        chunk_size_chars: int,
        max_total_input_chars: int,
    ) -> list[dict]:
        normalized_messages = [
            {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))}
            for item in messages
            if str(item.get("content", "")).strip()
        ]
        if not normalized_messages:
            return []

        total_chars = sum(len(item["content"]) for item in normalized_messages)
        longest_message = max(len(item["content"]) for item in normalized_messages)
        if total_chars <= max_input_chars and longest_message <= max_input_chars:
            return normalized_messages

        transcript = self._serialize_chat_messages(normalized_messages)
        if len(transcript) > max_total_input_chars:
            raise ValueError(
                "Conversation transcript exceeds the maximum supported size even with multipart chunking."
            )

        effective_chunk_size = max(1000, min(chunk_size_chars, max_input_chars - self._MULTIPART_OVERHEAD_CHARS))
        chunks = self._split_text_for_messages(transcript, effective_chunk_size)
        if len(chunks) <= 1:
            return normalized_messages

        total_parts = len(chunks)
        multipart_messages = [
            {
                "role": "user",
                "content": (
                    "The full conversation transcript is too large to fit in a single chat payload. "
                    f"It will be sent in {total_parts} consecutive parts. "
                    "Treat all parts as one continuous conversation transcript. Do not answer until the final instruction arrives. "
                    "The final USER entry in the transcript is the request you must answer."
                ),
            }
        ]
        for index, chunk in enumerate(chunks, start=1):
            multipart_messages.append(
                {
                    "role": "user",
                    "content": f"CONVERSATION PART {index}/{total_parts}\n\n{chunk}",
                }
            )
        multipart_messages.append(
            {
                "role": "user",
                "content": (
                    "All conversation parts have now been sent. "
                    "Use the full transcript above as the only conversation context and respond once to the final USER request."
                ),
            }
        )
        return multipart_messages

    @classmethod
    def _is_truncated_finish_reason(cls, finish_reason: str | None) -> bool:
        normalized = (finish_reason or "").strip().lower()
        return normalized in cls._TRUNCATED_FINISH_REASONS

    @staticmethod
    def _continuation_prompt() -> str:
        return "Continue exactly from where you stopped. Do not repeat prior text, do not restart, and do not summarize."

    @classmethod
    def _merge_text_segments(cls, base: str, continuation: str) -> str:
        if not base:
            return continuation
        if not continuation:
            return base

        max_overlap = min(len(base), len(continuation), 400)
        for overlap in range(max_overlap, 19, -1):
            if base.endswith(continuation[:overlap]):
                return base + continuation[overlap:]
        return base + continuation

    @staticmethod
    def _serialize_chat_messages(messages: list[dict]) -> str:
        lines: list[str] = []
        for item in messages:
            role = str(item.get("role", "user")).strip().upper() or "USER"
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"{role}:\n{content}")
        return "\n\n".join(lines)

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
