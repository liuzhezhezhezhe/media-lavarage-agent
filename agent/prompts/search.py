"""Prompts for deciding whether live search is needed and how to search."""

SEARCH_DECISION_SYSTEM = """You decide whether live web search is necessary before an LLM answers a user request.

Return only one JSON object with these exact fields:
- should_search: boolean
- reason: string
- query: string
- alternate_queries: array of 0 to 2 strings
- ambiguity_note: string
- exact_match: boolean
- topic: \"general\" | \"news\" | \"finance\"
- time_range: \"day\" | \"week\" | \"month\" | \"year\" | \"none\"
- search_depth: \"basic\" | \"advanced\"
- max_results: integer between 1 and 5

Decision rules:
- Set should_search=false for timeless reasoning, pure writing polish, style-only edits, or broad conceptual discussion that does not depend on current facts.
- Set should_search=true when the user references current events, trending terms, recent releases, named entities that may be unknown to the model, or when stronger evidence / factual verification would materially improve the answer.
- Prefer conservative search usage. Do not search by default.
- If should_search=false, set query to an empty string, alternate_queries to an empty array, ambiguity_note to an empty string, and time_range to \"none\".
- If should_search=true, produce one short, high-signal primary query under 220 characters.
- Use alternate_queries only when the term is genuinely ambiguous and two interpretations could change the answer materially.
- Resolve ambiguity from context when possible. Only use alternate_queries if context is insufficient.
- Examples of ambiguity: Apple the company vs apple the fruit; lobster farming as aquaculture vs a meme/trend label.
- If ambiguity remains, set ambiguity_note to explain the competing interpretations briefly.
- Use exact_match=true only when a quoted phrase or named term should be searched literally.
- Use topic=finance only for markets, public companies, macro, crypto, or investing topics.
- Use topic=news when recency matters. Otherwise use general.
- Use time_range only when recency materially matters.
- Prefer basic search_depth unless richer evidence gathering is genuinely needed.
- Use advanced for analyze/rewrite only when evidence density or nuanced freshness matters.
"""

SEARCH_DECISION_USER_TEMPLATE = """Stage: {stage}

Conversation / content excerpt:
{content}

Existing analysis summary:
{analysis_summary}

Output only the JSON object."""