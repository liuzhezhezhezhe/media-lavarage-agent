"""Format analysis results as Telegram MarkdownV2 messages."""
import re

# Characters that must be escaped in MarkdownV2
_ESCAPE_CHARS = r"\_*[]()~`>#+-=|{}.!"


def escape(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([" + re.escape(_ESCAPE_CHARS) + r"])", r"\\\1", text)


def _score_bar(score: int, total: int = 10) -> str:
    filled = min(max(int(score), 0), total)
    bar = "█" * filled + "░" * (total - filled)
    return bar


def format_analysis(analysis: dict, thought_id: int) -> str:
    idea_type = analysis.get("idea_type", "unknown")
    novelty = int(analysis.get("novelty_score") or 0)
    clarity = int(analysis.get("clarity_score") or 0)
    risk = analysis.get("risk_level", "unknown")
    publishable = analysis.get("publishable", False)
    summary = analysis.get("summary", "")
    recommended = analysis.get("recommended_platforms", [])
    platform_assessments = analysis.get("platform_assessments", [])

    pub_icon = "✅" if publishable else "❌"
    platforms_str = " → ".join(p.capitalize() for p in recommended) if recommended else "N/A"

    novelty_bar = _score_bar(novelty)
    clarity_bar = _score_bar(clarity)

    lines = [
        "📊 *Analysis Results*",
        "",
        f"Type: `{escape(idea_type)}`",
        f"Novelty: {novelty}/10  {escape(novelty_bar)}",
        f"Clarity: {clarity}/10  {escape(clarity_bar)}",
        f"Risk: `{escape(risk)}`",
        f"Publishable: {pub_icon}",
        "",
        f"💡 Summary: {escape(summary)}",
        "",
        f"📌 Recommended platforms: *{escape(platforms_str)}*",
        f"_\\(Record ID: {thought_id} — full version: /show {thought_id}\\)_",
    ]

    if isinstance(platform_assessments, list) and platform_assessments:
        lines.extend(["", "🧭 *Platform Assessments*"])
        for item in platform_assessments:
            if not isinstance(item, dict):
                continue
            platform = str(item.get("platform", "")).strip().lower()
            if not platform:
                continue
            allowed = bool(item.get("publishable", False))
            icon = "✅" if allowed else "❌"
            novelty_p = int(item.get("novelty_score") or 0)
            clarity_p = int(item.get("clarity_score") or 0)
            risk_p = str(item.get("risk_level", "unknown"))
            reason = str(item.get("reason", "")).strip()

            lines.append(
                f"\\- *{escape(platform.capitalize())}* {icon} \\| N:{novelty_p}/10 \\| C:{clarity_p}/10 \\| Risk: `{escape(risk_p)}`"
            )
            if reason:
                lines.append(f"  _{escape(reason)}_")

    return "\n".join(lines)


_PLATFORM_ICONS = {
    "x": "🐦",
    "medium": "📝",
    "substack": "📧",
    "reddit": "🤖",
}

_MAX_INLINE_CHARS = 3800  # leave headroom below 4096
_TELEGRAM_TEXT_HARD_LIMIT = 4096
_CHAT_SOFT_LIMIT = 3500


def _trim_dangling_escape(text: str) -> str:
    """Trim ending backslashes to avoid dangling MarkdownV2 escapes."""
    if not text:
        return text
    slash_count = 0
    for ch in reversed(text):
        if ch == "\\":
            slash_count += 1
        else:
            break
    if slash_count % 2 == 1:
        return text[:-1]
    return text


def _sanitize_code_block(text: str) -> str:
    """Make text safe for Telegram Markdown code blocks."""
    if not text:
        return ""
    return text.replace("```", "'''").strip()


def _extract_labeled_fields(content: str, labels: tuple[str, ...]) -> tuple[dict[str, str], str]:
    """Extract labeled lines and return (fields, body)."""
    fields: dict[str, str] = {}
    body = content or ""

    for label in labels:
        pattern = rf"(?im)^{label}\s*:\s*(.+)$"
        match = re.search(pattern, body)
        if match:
            fields[label] = match.group(1).strip()
            body = re.sub(pattern + r"\n?", "", body, count=1)

    return fields, body.strip()


def _extract_reddit_fields(content: str) -> tuple[dict[str, str], str]:
    """Extract Reddit PostType/Title/Body contract fields."""
    raw = (content or "").strip()
    fields: dict[str, str] = {}

    for label in ("PostType", "Title"):
        pattern = rf"(?im)^{label}\s*:\s*(.+)$"
        match = re.search(pattern, raw)
        if match:
            fields[label.lower()] = match.group(1).strip()
            raw = re.sub(pattern + r"\n?", "", raw, count=1)

    body_match = re.search(r"(?ims)^Body\s*:\s*(.*)$", raw)
    if body_match:
        inline_body = body_match.group(1).strip()
        raw = re.sub(r"(?ims)^Body\s*:\s*", "", raw, count=1).strip()
        if inline_body and not raw.startswith(inline_body):
            raw = f"{inline_body}\n\n{raw}".strip()

    return fields, raw.strip()


def _truncate_plain(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > max_len - 80:
        truncated = truncated[:last_space]
    return truncated


def _split_x_posts(content: str) -> tuple[str | None, list[str]]:
    """Parse X output into (post_type, posts)."""
    raw = (content or "").strip()
    if not raw:
        return None, []

    post_type = None
    match = re.search(r"(?im)^posttype\s*:\s*(tweet|tweet_pack|thread)\s*$", raw)
    if match:
        post_type = match.group(1).upper()
        raw = re.sub(r"(?im)^posttype\s*:\s*(tweet|tweet_pack|thread)\s*$\n?", "", raw, count=1).strip()

    parts = [part.strip() for part in re.split(r"\n\s*---\s*\n", raw) if part.strip()]
    if not parts and raw:
        parts = [raw]

    if not post_type:
        if len(parts) <= 1:
            post_type = "TWEET"
        else:
            has_index_markers = any(re.search(r"(?m)^\s*\d+\s*/\s*\d+", part) for part in parts)
            post_type = "THREAD" if has_index_markers else "TWEET_PACK"

    return post_type, parts


def _split_plain_chunks(text: str, max_len: int) -> list[str]:
    """Split plain text into chunks under max_len, preferring newline/space boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        cut = max_len
        newline_pos = remaining.rfind("\n", 0, max_len)
        space_pos = remaining.rfind(" ", 0, max_len)
        if newline_pos >= max_len - 200:
            cut = newline_pos
        elif space_pos >= max_len - 120:
            cut = space_pos
        chunk = remaining[:cut].rstrip()
        if not chunk:
            chunk = remaining[:max_len]
        chunks.append(chunk)
        remaining = remaining[len(chunk):].lstrip("\n ")

    if remaining:
        chunks.append(remaining)
    return chunks


def format_platform_output_full(platform: str, content: str) -> list[str]:
    """Return full platform output as one or more Telegram Markdown messages (no truncation)."""
    icon = _PLATFORM_ICONS.get(platform, "📄")
    platform_name = platform.capitalize()
    messages: list[str] = []

    if platform == "x":
        post_type, posts = _split_x_posts(content)
        if not posts:
            posts = [content.strip()] if content.strip() else ["(empty)"]
        post_type_text = {
            "TWEET": "Tweet",
            "TWEET_PACK": "Tweet pack",
            "THREAD": "Thread",
        }.get(post_type or "", "Tweet")
        label_prefix = "Thread" if (post_type or "").upper() == "THREAD" else "Tweet"

        for idx, post in enumerate(posts, start=1):
            sanitized_post = _sanitize_code_block(post)
            header = f"{icon} *{platform_name}*\n*Post Type*: `{post_type_text}`"
            label = f"*{label_prefix} {idx}*"
            prefix = f"{header}\n\n{label}\n```\n"
            suffix = "\n```"
            max_body_len = max(1, _MAX_INLINE_CHARS - len(prefix) - len(suffix))
            post_chunks = _split_plain_chunks(sanitized_post, max_body_len)

            if len(post_chunks) == 1:
                messages.append(prefix + post_chunks[0] + suffix)
            else:
                for part_idx, part in enumerate(post_chunks, start=1):
                    part_label = f"{label} (Part {part_idx}/{len(post_chunks)})"
                    part_prefix = f"{header}\n\n{part_label}\n```\n"
                    messages.append(part_prefix + part + suffix)
        return messages

    if platform in ("medium", "substack"):
        label_map = {
            "medium": ("title", "subtitle", "topics", "canonicalurl"),
            "substack": ("title", "subtitle", "emailsubject", "tags"),
        }
        fields, body = _extract_labeled_fields(content, label_map[platform])
        title = _sanitize_code_block(fields.get("title") or "(missing)")
        subtitle = _sanitize_code_block(fields.get("subtitle") or "(missing)")
        tags_or_topics = _sanitize_code_block(
            fields.get("topics") or fields.get("tags") or "(missing)"
        )
        canonical_or_subject = _sanitize_code_block(
            fields.get("canonicalurl") or fields.get("emailsubject") or "(missing)"
        )
        body = _sanitize_code_block(body or content)

        third_label = "Topics" if platform == "medium" else "Tags"
        fourth_label = "CanonicalURL" if platform == "medium" else "EmailSubject"

        meta_message = (
            f"{icon} *{platform_name}*\n\n"
            "*Title*\n"
            f"```\n{title}\n```\n"
            "*Subtitle*\n"
            f"```\n{subtitle}\n```\n"
            f"*{third_label}*\n"
            f"```\n{tags_or_topics}\n```\n"
            f"*{fourth_label}*\n"
            f"```\n{canonical_or_subject}\n```"
        )
        messages.append(meta_message)

        content_prefix = f"{icon} *{platform_name}*\n\n*Content*\n```\n"
        content_suffix = "\n```"
        max_body_len = max(1, _MAX_INLINE_CHARS - len(content_prefix) - len(content_suffix))
        body_chunks = _split_plain_chunks(body, max_body_len)
        if len(body_chunks) == 1:
            messages.append(content_prefix + body_chunks[0] + content_suffix)
        else:
            for idx, chunk in enumerate(body_chunks, start=1):
                prefix = f"{icon} *{platform_name}*\n\n*Content (Part {idx}/{len(body_chunks)})*\n```\n"
                messages.append(prefix + chunk + content_suffix)
        return messages

    if platform == "reddit":
        fields, body = _extract_reddit_fields(content)
        post_type = _sanitize_code_block(fields.get("posttype") or "(missing)")
        title = _sanitize_code_block(fields.get("title") or "(missing)")
        body = _sanitize_code_block(body or content)

        meta_message = (
            f"{icon} *{platform_name}*\n\n"
            "*Post Type*\n"
            f"```\n{post_type}\n```\n"
            "*Title*\n"
            f"```\n{title}\n```"
        )
        messages.append(meta_message)

        content_prefix = f"{icon} *{platform_name}*\n\n*Body*\n```\n"
        content_suffix = "\n```"
        max_body_len = max(1, _MAX_INLINE_CHARS - len(content_prefix) - len(content_suffix))
        body_chunks = _split_plain_chunks(body, max_body_len)
        if len(body_chunks) == 1:
            messages.append(content_prefix + body_chunks[0] + content_suffix)
        else:
            for idx, chunk in enumerate(body_chunks, start=1):
                prefix = f"{icon} *{platform_name}*\n\n*Body (Part {idx}/{len(body_chunks)})*\n```\n"
                messages.append(prefix + chunk + content_suffix)
        return messages

    sanitized_body = _sanitize_code_block(content)
    prefix = f"{icon} *{platform_name}*\n\n*Copy-ready content*\n```\n"
    suffix = "\n```"
    max_body_len = max(1, _MAX_INLINE_CHARS - len(prefix) - len(suffix))
    chunks = _split_plain_chunks(sanitized_body, max_body_len)
    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) == 1:
            messages.append(prefix + chunk + suffix)
        else:
            part_prefix = f"{icon} *{platform_name}*\n\n*Copy-ready content (Part {idx}/{len(chunks)})*\n```\n"
            messages.append(part_prefix + chunk + suffix)
    return messages


def format_platform_output(platform: str, content: str, thought_id: int) -> tuple[str, bool]:
    """
    Returns (message_text, was_truncated).
    Truncated content will include a note about /show <id>.
    """
    icon = _PLATFORM_ICONS.get(platform, "📄")
    platform_name = platform.capitalize()
    footer = f"\n\n_Truncated. Full version: /show {thought_id}_"

    if platform == "x":
        post_type, posts = _split_x_posts(content)
        if not posts:
            posts = [content.strip()] if content.strip() else ["(empty)"]
        post_type_text = {
            "TWEET": "Tweet",
            "TWEET_PACK": "Tweet pack",
            "THREAD": "Thread",
        }.get(post_type or "", "Tweet")

        lines = [f"{icon} *{platform_name}*", f"*Post Type*: `{post_type_text}`", ""]
        label_prefix = "Thread" if (post_type or "").upper() == "THREAD" else "Tweet"

        for idx, post in enumerate(posts, start=1):
            lines.append(f"*{label_prefix} {idx}*")
            lines.append("```")
            lines.append(_sanitize_code_block(post))
            lines.append("```")

        full = "\n".join(lines)
        if len(full) <= _MAX_INLINE_CHARS:
            return full, False

        compact_lines = [f"{icon} *{platform_name}*", f"*Post Type*: `{post_type_text}`", ""]
        running = "\n".join(compact_lines)
        for idx, post in enumerate(posts, start=1):
            block = "\n".join([
                f"*{label_prefix} {idx}*",
                "```",
                _sanitize_code_block(post),
                "```",
            ])
            candidate = (running + "\n" + block).strip()
            if len(candidate) + len(footer) > _MAX_INLINE_CHARS:
                break
            running = candidate

        if len(running) + len(footer) > _MAX_INLINE_CHARS:
            max_body_len = _MAX_INLINE_CHARS - len("\n".join(compact_lines)) - len(footer) - 20
            trimmed = _truncate_plain(_sanitize_code_block(posts[0]), max(max_body_len, 0))
            running = "\n".join(compact_lines + ["*Tweet 1*", "```", trimmed, "```"])
        return running + footer, True

    if platform in ("medium", "substack"):
        label_map = {
            "medium": ("title", "subtitle", "topics", "canonicalurl"),
            "substack": ("title", "subtitle", "emailsubject", "tags"),
        }
        fields, body = _extract_labeled_fields(content, label_map[platform])
        title = _sanitize_code_block(fields.get("title") or "(missing)")
        subtitle = _sanitize_code_block(fields.get("subtitle") or "(missing)")
        tags_or_topics = _sanitize_code_block(
            fields.get("topics") or fields.get("tags") or "(missing)"
        )
        canonical_or_subject = _sanitize_code_block(
            fields.get("canonicalurl") or fields.get("emailsubject") or "(missing)"
        )
        body = _sanitize_code_block(body or content)

        third_label = "Topics" if platform == "medium" else "Tags"
        fourth_label = "CanonicalURL" if platform == "medium" else "EmailSubject"

        prefix = (
            f"{icon} *{platform_name}*\n\n"
            "*Title*\n"
            f"```\n{title}\n```\n"
            "*Subtitle*\n"
            f"```\n{subtitle}\n```\n"
            f"*{third_label}*\n"
            f"```\n{tags_or_topics}\n```\n"
            f"*{fourth_label}*\n"
            f"```\n{canonical_or_subject}\n```\n"
            "*Content*\n"
            "```\n"
        )
        suffix = "\n```"

        full = prefix + body + suffix
        if len(full) <= _MAX_INLINE_CHARS:
            return full, False

        max_body_len = _MAX_INLINE_CHARS - len(prefix) - len(suffix) - len(footer)
        truncated_body = _truncate_plain(body, max(max_body_len, 0))
        return prefix + truncated_body + suffix + footer, True

    if platform == "reddit":
        fields, body = _extract_reddit_fields(content)
        post_type = _sanitize_code_block(fields.get("posttype") or "(missing)")
        title = _sanitize_code_block(fields.get("title") or "(missing)")
        body = _sanitize_code_block(body or content)

        prefix = (
            f"{icon} *{platform_name}*\n\n"
            "*Post Type*\n"
            f"```\n{post_type}\n```\n"
            "*Title*\n"
            f"```\n{title}\n```\n"
            "*Body*\n"
            "```\n"
        )
        suffix = "\n```"

        full = prefix + body + suffix
        if len(full) <= _MAX_INLINE_CHARS:
            return full, False

        max_body_len = _MAX_INLINE_CHARS - len(prefix) - len(suffix) - len(footer)
        truncated_body = _truncate_plain(body, max(max_body_len, 0))
        return prefix + truncated_body + suffix + footer, True

    body = _sanitize_code_block(content)
    prefix = f"{icon} *{platform_name}*\n\n*Copy-ready content*\n```\n"
    suffix = "\n```"
    full = prefix + body + suffix

    if len(full) <= _MAX_INLINE_CHARS:
        return full, False

    max_body_len = _MAX_INLINE_CHARS - len(prefix) - len(suffix) - len(footer)
    truncated_body = _truncate_plain(body, max(max_body_len, 0))
    return prefix + truncated_body + suffix + footer, True


def format_history(records: list[dict]) -> str:
    if not records:
        return "No records yet\\."

    lines = ["📋 *Recent Records*", ""]
    for r in records:
        idea_type = escape(r.get("idea_type") or "unknown")
        summary = escape((r.get("summary") or "")[:60])
        created = escape(r.get("created_at", "")[:10])
        rid = r["id"]
        novelty = int(r.get("novelty_score") or 0)
        lines.append(f"`#{rid}` {created} \\| `{idea_type}` \\| {novelty}/10")
        if summary:
            lines.append(f"     _{summary}_")
        lines.append(f"     👉 /show {rid}")
        lines.append("")

    return "\n".join(lines)


def format_full_record(thought: dict, outputs: list[dict]) -> list[str]:
    """Return list of messages for /show command."""
    messages = []

    # Analysis summary
    idea_type = escape(thought.get("idea_type") or "unknown")
    novelty = int(thought.get("novelty_score") or 0)
    clarity = int(thought.get("clarity_score") or 0)
    risk = escape(thought.get("risk_level") or "unknown")
    summary = escape(thought.get("summary") or "")
    created = escape(thought.get("created_at", "")[:19])
    source = escape(thought.get("source") or "text")
    pub = "✅" if thought.get("publishable") else "❌"

    msg1 = "\n".join([
        f"📊 *Record \\#{thought['id']}*",
        "",
        f"Date: `{created}`",
        f"Source: `{source}`",
        f"Type: `{idea_type}`",
        f"Novelty: {novelty}/10  {escape(_score_bar(int(novelty or 0)))}",
        f"Clarity: {clarity}/10  {escape(_score_bar(int(clarity or 0)))}",
        f"Risk: `{risk}`  Publishable: {pub}",
        "",
        f"💡 {summary}",
    ])
    messages.append(msg1)

    # Each platform output
    for output in outputs:
        platform = output.get("platform", "")
        content = output.get("content", "")
        icon = _PLATFORM_ICONS.get(platform, "📄")
        platform_name = escape(platform.capitalize())
        separator = escape("─" * 17)
        escaped_content = escape(content)

        msg = f"{icon} *{platform_name}*\n{separator}\n{escaped_content}"
        # Split into chunks if too long
        for chunk in _split_message(msg):
            messages.append(chunk)

    return messages


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while len(text) > max_len:
        chunk = _trim_dangling_escape(text[:max_len])
        if not chunk:
            chunk = text[:max_len]
        chunks.append(chunk)
        text = text[len(chunk):]
    if text:
        chunks.append(text)
    return chunks


def normalize_chat_markdown(text: str) -> str:
    """Normalize common Markdown to Telegram Markdown-compatible syntax."""
    if not text:
        return ""

    normalized = text.strip().replace("\r\n", "\n")
    normalized = re.sub(r"\*\*(.+?)\*\*", r"*\1*", normalized, flags=re.DOTALL)
    normalized = re.sub(r"__(.+?)__", r"_\1_", normalized, flags=re.DOTALL)
    return normalized


def split_chat_reply(text: str, max_len: int = _CHAT_SOFT_LIMIT) -> list[str]:
    """Split chat replies into Telegram-safe chunks.

    Telegram sendMessage text limit is 1-4096 chars after entities parsing.
    We use a lower soft limit to reduce parse-mode edge failures.
    """
    if not text:
        return [""]

    normalized = normalize_chat_markdown(text)
    if len(normalized) <= max_len:
        return [normalized]

    chunks: list[str] = []
    paragraphs = [p for p in re.split(r"\n{2,}", normalized) if p is not None]
    current = ""

    for para in paragraphs:
        para = para.strip("\n")
        if not para:
            continue

        candidate = para if not current else f"{current}\n\n{para}"
        if len(candidate) <= max_len:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(para) <= max_len:
            current = para
            continue

        chunks.extend(_split_plain_chunks(para, max_len))

    if current:
        chunks.append(current)

    if not chunks:
        return _split_plain_chunks(normalized, max_len)

    return chunks
