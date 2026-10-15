"""Research agent: picks a random topic in a category, researches it on the web,
and writes a fun, newsletter-style summary."""

from dotenv import load_dotenv
load_dotenv()
import random
import sys

import anthropic



MODEL = "claude-opus-5-5"
MAX_CONTINUATIONS = 5

SYSTEM_PROMPT = """You write a short, fun newsletter segment about a randomly chosen topic.

1. Pick one specific, surprising topic inside the category you're given. Prefer
   things most readers haven't heard of over the obvious picks.
2. Use web search to learn about it and check your facts.
3. Write the segment in Markdown:
   - A catchy title (# heading)
   - A one-line hook
   - 3-5 short paragraphs that explain the topic in a playful, conversational tone
   - A "Fun fact" line at the end
   - A "Sources" list with the URLs you relied on

Keep it under 400 words and only include facts your sources support."""

# Nudges Claude toward a different corner of the category on each run, so
# repeated calls with the same category don't keep landing on the same topic.
ANGLES = [
    "a person", "a place", "an invention", "an event in history", "a strange record",
    "a discovery", "a tradition", "a mistake that turned out well", "a rivalry",
    "something tiny", "something enormous", "something from before 1800",
    "something from the last 10 years",
]

client = anthropic.Anthropic()


def research_topic(category: str) -> str:
    """Return a Markdown summary of a random topic in `category`."""
    angle = random.choice(ANGLES)
    messages = [{
        "role": "user",
        "content": f"Category: {category}\nFor variety, make the topic {angle}.",
    }]

    for _ in range(MAX_CONTINUATIONS):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        # Web search runs server-side; a long search loop pauses and must be resumed.
        if response.stop_reason != "pause_turn":
            break
        messages = messages[:1] + [{"role": "assistant", "content": response.content}]

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined this request: {response.stop_details}")

    # Skip the "let me search..." narration and keep only the text after the last search.
    blocks = response.content
    last_tool = max((i for i, b in enumerate(blocks) if b.type != "text" and b.type != "thinking"), default=-1)
    text = "".join(b.text for b in blocks[last_tool + 1:] if b.type == "text")
    if not text.strip():
        raise RuntimeError(f"No summary returned (stop_reason={response.stop_reason})")
    return text.strip()


if __name__ == "__main__":
    category = " ".join(sys.argv[1:]) or "science"
    print(research_topic(category))
