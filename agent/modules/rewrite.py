from agent.llm.base import LLMClient, LLMResponse
from agent.llm.web_search import SearchAgent
from agent.prompts import rewrite as prompts


def _build_reddit_priority(analysis: dict, key_points: list[str]) -> str:
    """Return Reddit mode guidance based on the analyzed source type."""
    idea_type = (analysis.get("idea_type") or "").strip().lower()

    type_guidance: dict[str, tuple[str, list[str]]] = {
        "opinion": (
            "DISCUSSION_POST",
            [
                "Lead with the take, not the backstory.",
                "Frame the post around one disagreement, tradeoff, or tension people can react to.",
            ],
        ),
        "analysis": (
            "DISCUSSION_POST",
            [
                "Turn the analysis into one interpretable pattern or implication, not a full explainer.",
                "Make the body answer: what should this community notice or reconsider?",
            ],
        ),
        "news": (
            "DISCUSSION_POST",
            [
                "Do not rewrite the news article. Focus on the one angle this community is most likely to debate.",
                "Assume readers can look up details elsewhere; keep only the context needed for discussion.",
            ],
        ),
        "tutorial": (
            "QUESTION_POST",
            [
                "Do not post a step-by-step guide by default.",
                "Reframe the material into a practical question, workflow tradeoff, or 'how are people doing this?' post.",
            ],
        ),
        "story": (
            "EXPERIENCE_POST",
            [
                "Keep the personal or observed moment, but strip it down to the part others can relate to.",
                "Use one concrete detail, then pivot quickly to the broader pattern or question.",
            ],
        ),
        "essay": (
            "EXPERIENCE_POST",
            [
                "Do not preserve the full reflective arc.",
                "Condense it into one lived observation or thought that invites other people to compare notes.",
            ],
        ),
        "thread": (
            "DISCUSSION_POST",
            [
                "Do not convert each point into a list.",
                "Pick the single most discussable point and build the post around that.",
            ],
        ),
    }

    preferred_type, bullets = type_guidance.get(
        idea_type,
        (
            "DISCUSSION_POST",
            [
                "Favor the most discussable angle over the most complete summary.",
                "Make the body feel native to a subreddit conversation, not to a publishing platform.",
            ],
        ),
    )

    guidance_lines = [
        "\n\nRUNTIME PRIORITY FOR THIS INPUT:",
        f"- Preferred Reddit PostType for this source: {preferred_type}.",
    ]
    guidance_lines.extend(f"- {bullet}" for bullet in bullets)
    if len(key_points) >= 3:
        guidance_lines.append(
            "- The source contains multiple points. Choose the one angle most likely to trigger replies and ignore the rest."
        )
    return "\n".join(guidance_lines)


async def rewrite(
    content: str,
    platform: str,
    analysis: dict,
    llm: LLMClient,
    user_style: str | None = None,
    search_agent: SearchAgent | None = None,
) -> str:
    """Generate platform-specific content version."""
    platform_instruction = prompts.PLATFORM_INSTRUCTIONS.get(
        platform,
        f"Write content optimized for {platform}.",
    )
    key_points = analysis.get("key_points", [])
    if platform == "x" and len(key_points) >= 2:
        platform_instruction += (
            "\n\nRUNTIME PRIORITY FOR THIS INPUT:\n"
            "- The source contains multiple key points. Prefer 2–5 standalone tweets"
            " separated by a line containing only '---'.\n"
            "- Do not write them as a dependency thread; each tweet must work on its own.\n"
            "- Set PostType to TWEET_PACK unless a true THREAD is necessary."
        )
    if platform == "x":
        platform_instruction += (
            "\n\nRUNTIME OUTPUT CONTRACT (strict):\n"
            "- First non-empty line must be: PostType: TWEET or PostType: TWEET_PACK or PostType: THREAD.\n"
            "- Then one blank line, then post content.\n"
            "- If PostType is TWEET_PACK or THREAD, separate each post with a line containing only '---'."
        )
    if platform == "medium":
        platform_instruction += (
            "\n\nRUNTIME OUTPUT CONTRACT (strict):\n"
            "- Start with exactly four labeled lines in this order:\n"
            "  Title: ...\n"
            "  Subtitle: ...\n"
            "  Topics: ...\n"
            "  CanonicalURL: ...\n"
            "- Then add one blank line, then the full body content.\n"
            "- Do not omit any of the four labels, and do not rename labels."
        )
    if platform == "substack":
        platform_instruction += (
            "\n\nRUNTIME OUTPUT CONTRACT (strict):\n"
            "- Start with exactly four labeled lines in this order:\n"
            "  Title: ...\n"
            "  Subtitle: ...\n"
            "  EmailSubject: ...\n"
            "  Tags: ...\n"
            "- Then add one blank line, then the full body content.\n"
            "- Do not omit any of the four labels, and do not rename labels."
        )
    if platform == "reddit":
        platform_instruction += _build_reddit_priority(analysis, key_points)
        platform_instruction += (
            "\n\nRUNTIME OUTPUT CONTRACT (strict):\n"
            "- Start with exactly three labeled lines in this order:\n"
            "  PostType: DISCUSSION_POST or QUESTION_POST or EXPERIENCE_POST\n"
            "  Title: ...\n"
            "  Body:\n"
            "- Then add one blank line, then the full post body.\n"
            "- The body must end with one open-ended discussion question.\n"
            "- Do not output an article, essay, or newsletter-style structure.\n"
            "- Do not omit any label, and do not rename labels."
        )
    key_points_str = "\n".join(f"- {p}" for p in key_points) if key_points else "(none extracted)"
    style_instruction = (user_style or "").strip() or "(none)"
    web_context = ""
    if search_agent:
        web_context = await search_agent.build_prompt_context(
            stage="rewrite",
            text=content,
            llm=llm,
            analysis=analysis,
        )

    user_prompt = prompts.USER_TEMPLATE.format(
        content=content,
        summary=analysis.get("summary", ""),
        key_points=key_points_str,
        style_instruction=style_instruction,
        web_context=web_context,
        platform_instruction=platform_instruction,
        platform=platform,
    )

    max_tokens = 2048 if platform in ("medium", "substack") else 512

    response: LLMResponse = await llm.complete_safe(
        system=prompts.SYSTEM,
        user=user_prompt,
        max_tokens=max_tokens,
    )
    return response.content.strip()
