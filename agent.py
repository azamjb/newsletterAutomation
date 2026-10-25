"""Research agents for the newsletter:
- select_mover: picks the biggest mover that has a clear news cause.
- research_mover: explains, from the news, why a stock made a big move.
- find_image: picks a Wikimedia Commons picture for the story."""

from dotenv import load_dotenv
load_dotenv()
import html
import json
import re
import sys
from typing import Optional

import anthropic
import httpx

MODEL = "claude-sonnet-5-5"
MAX_CONTINUATIONS = 5

# Claude Sonnet 5.5 pricing, used to log an estimated cost per run.
PRICE_PER_INPUT_TOKEN = 2.00 / 1_000_000
PRICE_PER_OUTPUT_TOKEN = 10.00 / 1_000_000
PRICE_PER_WEB_SEARCH = 10.00 / 1_000

STOCK_PROMPT = """You write the daily issue of a newsletter that teaches readers how the
stock market reacts to news. Each issue explains one big stock move from the previous
trading day.

You'll be given the stock's market data. Those numbers are accurate: use them as given,
and don't state other price or volume figures.

1. Use web search to find out why the stock moved: the specific news behind it
   (earnings, guidance, an FDA decision, a deal, a lawsuit, an analyst call, an executive
   change, industry or economic news). Look for reporting from that trading day or just
   before it, and confirm the reason with at least two sources.
2. Explain the move through the news only. No chart patterns, technical analysis or
   valuation modeling.
3. If no clear reason turns up, say so honestly and explain what investors may be
   reacting to. Never invent a reason.

Write the issue in Markdown with exactly these parts:

# A specific, catchy headline
A one-line hook (no heading).

## What happened
The news, in plain language.

## Why the market cared
Why this news changed what investors think the company is worth. This is the teaching
part, so take your time on it.

## The lesson
One general takeaway about how markets react to this kind of news, in 1-3 sentences,
useful beyond this one company.

## What to watch next
Upcoming events or open questions.

## Sources
A list of the URLs you relied on.

Write for curious beginners: define jargon briefly the first time it appears (e.g.
"guidance", "Phase 3 trial"). Be lively but accurate. Stay under 450 words. Never tell
readers to buy, sell or hold anything."""

CHECK_PROMPT = """You screen stocks for a newsletter that teaches readers how the stock
market reacts to news. You're given one stock that made a big move on a trading day.
Do a quick web search to find out whether a clear, confirmed news event explains the move
(earnings, guidance, an FDA or trial result, a deal, a lawsuit, an executive change, a
competitor's news). Speculation, a vague "shares fell" with no reason, or news from weeks
earlier doesn't count.

Reply with exactly these two lines and nothing else:
VERDICT: CLEAR or UNCLEAR
CAUSE: <one sentence: the news that caused the move, or what you found if it's unclear>"""

IMAGE_PROMPT = """You pick one picture to illustrate a newsletter story.

Use the search_images tool to search Wikimedia Commons for a picture of the
story's specific subject (not just the broad category). When the subject is a
company, good pictures show the company itself: its headquarters, a store or
factory, its products, or the thing that's in the news (a drug, a vehicle, a
device). A plain logo is a last resort. Search with short, concrete keywords like
a name, place or object from the story. If the results don't fit, try a few
different searches (for example a broader term, or a related product or place)
before giving up.

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


def _log_usage(label: str, responses: list) -> None:
    """Print token use and an estimated cost for a set of API responses."""
    input_tokens = sum(r.usage.input_tokens for r in responses)
    output_tokens = sum(r.usage.output_tokens for r in responses)
    searches = sum(
        (getattr(r.usage.server_tool_use, "web_search_requests", 0) or 0)
        for r in responses if getattr(r.usage, "server_tool_use", None)
    )
    cost = (input_tokens * PRICE_PER_INPUT_TOKEN + output_tokens * PRICE_PER_OUTPUT_TOKEN
            + searches * PRICE_PER_WEB_SEARCH)
    print(f"[cost] {label}: {input_tokens:,} input + {output_tokens:,} output tokens, "
          f"{searches} web searches = ~${cost:.3f}")


def _run_agent(system: str, user_content: str, tools: list, label: str = "agent",
               effort: str = "medium") -> str:
    """Run one agent turn with server-side tools and return its final text."""
    messages = [{"role": "user", "content": user_content}]
    responses = []

    for _ in range(MAX_CONTINUATIONS):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        responses.append(response)
        # Web tools run server-side; a long tool loop pauses and must be resumed.
        if response.stop_reason != "pause_turn":
            break
        messages = messages[:1] + [{"role": "assistant", "content": response.content}]

    _log_usage(label, responses)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined this request: {response.stop_details}")

    # Skip the "let me search..." narration and keep only the text after the last tool call.
    blocks = response.content
    last_tool = max((i for i, b in enumerate(blocks) if b.type != "text" and b.type != "thinking"), default=-1)
    text = "".join(b.text for b in blocks[last_tool + 1:] if b.type == "text")
    if not text.strip():
        raise RuntimeError(f"No text returned (stop_reason={response.stop_reason})")
    return text.strip()


def _format_mover(mover: dict, trading_day: str) -> str:
    """The market data handed to the agent, so it never has to look numbers up."""
    def billions(n):
        return f"${n / 1e9:,.1f}B" if n else "unknown"
    lines = [
        f"Company: {mover['company_name']} ({mover['ticker']}, {mover['exchange']})",
        f"Trading day: {trading_day}",
        f"Move: {mover['change_percent']:+.2f}% (${mover['previous_close']:,.2f} -> ${mover['price']:,.2f})",
        f"Trading volume: {mover['volume']:,} shares"
        + (f", {mover['volume_vs_average']}x its normal volume" if mover.get("volume_vs_average") else ""),
        f"Market cap: {billions(mover.get('market_cap'))}",
        f"52-week range: ${mover['year_low']} - ${mover['year_high']}" if mover.get("year_low") else "",
        f"Sector: {mover.get('sector')} / {mover.get('industry')}",
        f"About the company: {(mover.get('description') or '')[:800]}",
    ]
    return "\n".join(line for line in lines if line)


def _format_candidate(c: dict) -> str:
    volume = f", {c['volume_vs_average']}x normal volume" if c.get("volume_vs_average") else ""
    cap = f"${c['market_cap'] / 1e9:,.1f}B" if c.get("market_cap") else "unknown size"
    return (f"- {c['ticker']} ({c['company_name']}, {c.get('industry') or c.get('sector')}): "
            f"{c['change_percent']:+.2f}%{volume}, market cap {cap}")


def _check_news(candidate: dict, trading_day: str) -> tuple[bool, str]:
    """Quick news check on one candidate: (is there a clear cause?, one-line cause)."""
    reply = _run_agent(
        CHECK_PROMPT,
        f"Trading day: {trading_day}\nStock:\n{_format_candidate(candidate)}",
        [{"type": "web_search_20260209", "name": "web_search", "max_uses": 2}],
        label=f"{candidate['ticker']} news check",
        # A quick yes/no news check doesn't need deep reasoning.
        effort="low",
    )
    verdict = re.search(r"^VERDICT:\s*(\w+)", reply, re.MULTILINE)
    cause = re.search(r"^CAUSE:\s*(.+)$", reply, re.MULTILINE)
    clear = bool(verdict) and verdict.group(1).upper() == "CLEAR"
    return clear, cause.group(1).strip() if cause else reply[:200]


def select_mover(candidates: list[dict], trading_day: str) -> dict:
    """Pick today's stock: check candidates in order of move size and take the first
    with a clear news cause, so usually only the biggest mover gets checked.
    Returns {"mover", "reason", "notes"}. If none has a clear cause (or the checks
    fail), falls back to the biggest move so an issue can always go out."""
    skipped = []  # tickers checked and passed over for lack of a clear cause
    findings = []
    for candidate in candidates:
        try:
            clear, cause = _check_news(candidate, trading_day)
        except (anthropic.APIError, RuntimeError) as e:
            print(f"News check failed for {candidate['ticker']}: {e}")
            break
        findings.append(f"{candidate['ticker']} - {cause}")
        print(f"{candidate['ticker']}: {'clear' if clear else 'unclear'} - {cause}")
        if clear:
            if skipped:
                they = "it" if len(skipped) == 1 else "them"
                reason = f"{', '.join(skipped)} moved more, but no clear news explained {they}."
            else:
                reason = "The day's biggest move among large companies, with a clear news cause."
            return {"mover": candidate, "reason": reason, "notes": cause}
        skipped.append(candidate["ticker"])

    print("No candidate had a clear news cause, using the biggest move")
    return {"mover": candidates[0], "reason": None, "notes": findings[0] if findings else None}


def research_mover(mover: dict, trading_day: str, notes: Optional[str] = None) -> str:
    """Return a Markdown issue explaining, from the news, why `mover` moved.
    `notes` are the selection step's findings, a head start for the research."""
    content = _format_mover(mover, trading_day)
    if notes:
        content += ("\n\nNotes from a quick news check earlier (a starting point; verify "
                    f"before relying on them):\n{notes}")
    return _run_agent(
        STOCK_PROMPT,
        content,
        [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}],
        label=f"{mover['ticker']} research",
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
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text))).strip()


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
        # Outlook and some other email clients can't display WebP.
        if not url or url.lower().endswith(".webp"):
            continue
        artist = _strip_html(meta.get("Artist", {}).get("value", ""))
        if len(artist) > 80:
            artist = artist[:77].rstrip(" ,.") + "..."
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        results.append({
            "url": url,
            "title": page.get("title", "").removeprefix("File:"),
            "description": _strip_html(meta.get("ImageDescription", {}).get("value", ""))[:300],
            "credit": ", ".join(p for p in (artist, license_name) if p) + " via Wikimedia Commons",
        })
    return results


def find_image(subject: str, summary: str) -> Optional[dict]:
    """Have Claude search Wikimedia Commons for a picture that fits the story.
    `subject` is what the story is about, e.g. a company name or a category.
    Returns {url, caption, credit}, or None if no usable image turns up (the
    newsletter still goes out without one)."""
    messages = [{"role": "user", "content": f"Subject: {subject}\n\nStory:\n{summary}"}]
    seen: dict[str, dict] = {}  # every result the tool returned, keyed by url
    responses = []

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
            responses.append(response)
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
    finally:
        if responses:
            _log_usage("image search", responses)

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
    # Research the latest biggest mover from the command line: python agent.py
    from market_data import get_biggest_mover
    trading_day, _, candidates = get_biggest_mover()
    if not candidates:
        sys.exit("No movers passed the filters for the latest trading day")
    selection = select_mover(candidates, trading_day)
    mover = selection["mover"]
    story = research_mover(mover, trading_day, selection["notes"])
    print(story)
    print("\nImage:", find_image(mover["company_name"], story))
