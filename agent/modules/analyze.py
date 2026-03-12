import json
import re
from agent.llm.base import LLMClient, LLMResponse
from agent.llm.web_search import SearchAgent
from agent.prompts import analyze as prompts


async def analyze(content: str, llm: LLMClient, search_agent: SearchAgent | None = None) -> dict:
    """Call LLM to analyze content. Returns parsed analysis dict."""
    web_context = ""
    if search_agent:
        web_context = await search_agent.build_prompt_context(
            stage="analyze",
            text=content,
            llm=llm,
        )

    user_prompt = prompts.USER_TEMPLATE.format(
        content=content,
        web_context=web_context,
    )
    response: LLMResponse = await llm.complete(
        system=prompts.SYSTEM,
        user=user_prompt,
        max_tokens=1024,
    )
    return _parse_json(response.content)


def _parse_json(raw: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    # Strip ```json ... ``` fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        # Fallback: try to find JSON object in the response
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        # Return fail-closed defaults so malformed model output is never
        # treated as publishable content.
        return {
            "idea_type": "essay",
            "novelty_score": 0,
            "clarity_score": 0,
            "publishable": False,
            "platform_assessments": [
                {
                    "platform": "x",
                    "novelty_score": 0,
                    "clarity_score": 0,
                    "publishable": False,
                    "risk_level": "unknown",
                    "summary": "",
                    "key_points": [],
                    "reason": "analysis parse failed",
                },
                {
                    "platform": "medium",
                    "novelty_score": 0,
                    "clarity_score": 0,
                    "publishable": False,
                    "risk_level": "unknown",
                    "summary": "",
                    "key_points": [],
                    "reason": "analysis parse failed",
                },
                {
                    "platform": "substack",
                    "novelty_score": 0,
                    "clarity_score": 0,
                    "publishable": False,
                    "risk_level": "unknown",
                    "summary": "",
                    "key_points": [],
                    "reason": "analysis parse failed",
                },
                {
                    "platform": "reddit",
                    "novelty_score": 0,
                    "clarity_score": 0,
                    "publishable": False,
                    "risk_level": "unknown",
                    "summary": "",
                    "key_points": [],
                    "reason": "analysis parse failed",
                },
            ],
            "risk_level": "unknown",
            "summary": "Analysis parsing failed. Please retry.",
            "recommended_platforms": [],
            "key_points": [],
        }
