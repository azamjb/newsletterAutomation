"""Research agent: picks a random topic in a category, researches it on the web,
and writes a fun, newsletter-style summary."""

from dotenv import load_dotenv
load_dotenv()
import json
import random
import re
import sys
from typing import Optional

import anthropic
import httpx

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

IMAGE_PROMPT = """You pick one picture to illustrate a newsletter story.

Use the search_images tool to search Wikimedia Commons for a picture of the
story's specific topic (not just the broad category). Search with short, concrete
keywords like a name, place or object from the story. If the results don't fit,
try a few different searches (for example a broader term, or a related person or
place) before giving up.

When you've chosen, reply with exactly these two lines and nothing else:
IMAGE_URL: <the url of your chosen result, copied exactly>
CAPTION: <one short sentence describing what the picture shows>

If nothing suitable turns up after a few searches, reply with: IMAGE_URL: NONE"""

IMAGE_SEARCH_TOOL = {
    "name": "search_images",
    "description": "Search Wikimedia Commons for freely licensed images. Returns up to 8 "
                   "results, each with an image url, title, description and license.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search keywords, e.g. 'Mokele-mbembe'"}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}
MAX_IMAGE_SEARCH_TURNS = 6

client = anthropic.Anthropic()


def _run_agent(system: str, user_content: str, tools: list) -> str:
    """Run one agent turn with server-side tools and return its final text."""
    messages = [{"role": "user", "content": user_content}]

    for _ in range(MAX_CONTINUATIONS):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        # Web tools run server-side; a long tool loop pauses and must be resumed.
        if response.stop_reason != "pause_turn":
            break
        messages = messages[:1] + [{"role": "assistant", "content": response.content}]

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined this request: {response.stop_details}")

    # Skip the "let me search..." narration and keep only the text after the last tool call.
    blocks = response.content
    last_tool = max((i for i, b in enumerate(blocks) if b.type != "text" and b.type != "thinking"), default=-1)
    text = "".join(b.text for b in blocks[last_tool + 1:] if b.type == "text")
    if not text.strip():
        raise RuntimeError(f"No text returned (stop_reason={response.stop_reason})")
    return text.strip()


def research_topic(category: str) -> str:
    """Return a Markdown summary of a random topic in `category`."""
    angle = random.choice(ANGLES)
    return _run_agent(
        SYSTEM_PROMPT,
        f"Category: {category}\nFor variety, make the topic {angle}.",
        [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
    )


# Wikimedia rejects (HTTP 429) requests whose User-Agent has no contact URL or email.
# https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = "newsletterAutomation/1.0 (https://github.com/azamjb/newsletterAutomation)"


def _is_image(url: str) -> bool:
    """Check that `url` actually serves an image, so the email never shows a broken picture."""
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=10,
                          headers={"User-Agent": USER_AGENT}) as r:
            ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
            if not ok:
                print(f"Image check failed: HTTP {r.status_code}, {r.headers.get('content-type')}")
            return ok
    except httpx.HTTPError:
        return False


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def search_commons(query: str) -> list[dict]:
    """Search Wikimedia Commons for images. Each result has a direct, email-friendly
    image url (resized to 800px wide) plus the description and credit."""
    r = httpx.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query", "format": "json",
            "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": 6, "gsrlimit": 8,
            "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 800,
            "iiextmetadatafilter": "ImageDescription|Artist|LicenseShortName",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    r.raise_for_status()
    results = []
    for page in r.json().get("query", {}).get("pages", {}).values():
        info = page.get("imageinfo", [{}])[0]
        meta = info.get("extmetadata", {})
        # Drop the "?utm_source=..." tracking suffix so the url is short and easy to copy exactly.
        url = (info.get("thumburl") or info.get("url") or "").split("?")[0]
        if not url:
            continue
        artist = _strip_html(meta.get("Artist", {}).get("value", ""))
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        results.append({
            "url": url,
            "title": page.get("title", "").removeprefix("File:"),
            "description": _strip_html(meta.get("ImageDescription", {}).get("value", ""))[:300],
            "credit": ", ".join(p for p in (artist, license_name) if p) + " via Wikimedia Commons",
        })
    return results


def find_image(category: str, summary: str) -> Optional[dict]:
    """Have Claude search Wikimedia Commons for a picture that fits the story.
    Returns {url, caption, credit}, or None if no usable image turns up (the
    newsletter still goes out without one)."""
    messages = [{"role": "user", "content": f"Category: {category}\n\nStory:\n{summary}"}]
    seen: dict[str, dict] = {}  # every result the tool returned, keyed by url

    try:
        for _ in range(MAX_IMAGE_SEARCH_TURNS):
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=IMAGE_PROMPT,
                messages=messages,
                tools=[IMAGE_SEARCH_TOOL],
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                query = block.input.get("query", "")
                print(f"Image search: {query!r}")
                try:
                    found = search_commons(query)
                    seen.update({r["url"]: r for r in found})
                    content = json.dumps(found) if found else "No results. Try different keywords."
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
                except httpx.HTTPError as e:
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": f"Search failed: {e}", "is_error": True})
            messages.append({"role": "user", "content": tool_results})
        else:
            print("Image search gave up after too many searches")
            return None
    except anthropic.APIError as e:
        print(f"Image search failed: {e}")
        return None

    if response.stop_reason == "refusal":
        print(f"Image search declined: {response.stop_details}")
        return None

    reply = "".join(b.text for b in response.content if b.type == "text")
    fields = dict(re.findall(r"^(IMAGE_URL|CAPTION):\s*(.+)$", reply, re.MULTILINE))
    url = fields.get("IMAGE_URL", "").strip()
    # Only accept a url the search actually returned, so the credit line is accurate
    # and Claude can't hand back a made-up link.
    if url not in seen or not _is_image(url):
        print(f"No usable image found (got: {url or reply[:100]!r})")
        return None
    choice = seen[url]
    return {"url": url, "caption": fields.get("CAPTION", "").strip() or choice["title"], "credit": choice["credit"]}


if __name__ == "__main__":
    category = " ".join(sys.argv[1:]) or "science"
    summary = research_topic(category)
    print(summary)
    print("\nImage:", find_image(category, summary))
