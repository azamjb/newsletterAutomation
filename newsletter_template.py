"""HTML email template for the newsletter.

Email clients support only a small, old subset of HTML/CSS (Outlook in particular
ignores flexbox, grid and most <style> rules), so the layout is built from tables
with inline styles. That's deliberate; don't "modernize" it.

Run `python newsletter_template.py` to write preview.html with sample content.
"""

import datetime
import hashlib
import html
import re
from typing import Optional

import markdown

NEWSLETTER_NAME = "Why It Moved"
TAGLINE = "One big stock move a day, and what it teaches about markets."
DISCLAIMER = "For learning only, not financial advice. Nothing here is a recommendation to buy or sell."

# Each issue gets a color theme, chosen from the category so the same category
# always looks the same. "deep" is dark enough for white text and for text on "tint".
THEMES = [
    {"name": "coral",  "accent": "#FF6B6B", "deep": "#C0392B", "tint": "#FFF0EE"},
    {"name": "violet", "accent": "#8E7CFF", "deep": "#5B3FD1", "tint": "#F2EFFF"},
    {"name": "teal",   "accent": "#2EC4B6", "deep": "#00796B", "tint": "#E6F7F5"},
    {"name": "amber",  "accent": "#FFB627", "deep": "#A15C00", "tint": "#FFF6E3"},
    {"name": "ocean",  "accent": "#4EA8DE", "deep": "#1D5FA0", "tint": "#EAF4FC"},
    {"name": "berry",  "accent": "#F06595", "deep": "#B0215F", "tint": "#FDEEF4"},
]

INK = "#1F2040"        # headings
TEXT = "#3C3D55"       # body copy
MUTED = "#7A7B90"      # captions, sources
PAPER = "#F5F1E8"      # page background around the card
SERIF = "Georgia, 'Times New Roman', Times, serif"
SANS = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


UP_COLOR = "#0F8A5F"    # green for gains
DOWN_COLOR = "#C0392B"  # red for losses


def pick_theme(category: str, direction: Optional[str] = None) -> dict:
    """Teal for a stock that rose, coral for one that fell; otherwise one picked
    from the category, so the same category always gets the same colors."""
    if direction in ("up", "down"):
        return next(t for t in THEMES if t["name"] == ("teal" if direction == "up" else "coral"))
    index = int(hashlib.md5(category.encode()).hexdigest(), 16) % len(THEMES)
    return THEMES[index]


def _money(n: Optional[float]) -> str:
    if n is None:
        return "–"
    if n >= 1e12:
        return f"${n / 1e12:.2f}T"
    if n >= 1e9:
        return f"${n / 1e9:.1f}B"
    if n >= 1e6:
        return f"${n / 1e6:.0f}M"
    return f"${n:,.2f}"


def _styled(fragment: str, theme: dict, size: int = 16, color: str = TEXT) -> str:
    """Add inline styles to the plain tags the markdown library produces."""
    p = f"margin:0 0 16px;font-family:{SANS};font-size:{size}px;line-height:1.65;color:{color};"
    rules = {
        "<p>": f'<p style="{p}">',
        "<ul>": '<ul style="margin:0 0 16px;padding-left:22px;">',
        "<ol>": '<ol style="margin:0 0 16px;padding-left:22px;">',
        "<li>": f'<li style="{p}margin:0 0 6px;">',
        "<h2>": f'<h2 style="margin:28px 0 10px;font-family:{SERIF};font-size:22px;line-height:1.3;color:{INK};">',
        "<h3>": f'<h3 style="margin:24px 0 8px;font-family:{SERIF};font-size:19px;line-height:1.3;color:{INK};">',
        "<blockquote>": f'<blockquote style="margin:0 0 16px;padding:0 0 0 16px;border-left:3px solid {theme["accent"]};">',
        "<strong>": f'<strong style="color:{INK};">',
    }
    for tag, replacement in rules.items():
        fragment = fragment.replace(tag, replacement)
    return fragment.replace("<a ", f'<a style="color:{theme["deep"]};text-decoration:underline;" ')


def _md(text: str) -> str:
    # Turn bare URLs into links labelled with just the site name: a long unbroken URL
    # would otherwise stretch the email wider than a phone screen.
    def link(m: re.Match) -> str:
        url = m.group(1)
        domain = re.sub(r"^www\.", "", url.split("/")[2])
        return f"[{domain}]({url})"
    text = re.sub(r"(?<![(<\"\[])(https?://[^\s)>\]]+)", link, text)
    return markdown.markdown(text)


def _strip_label(block: str, label: str) -> str:
    """Remove a leading label such as '**Fun fact:**' or '## Fun Fact' from a block."""
    start = block.lower().find(label) + len(label)
    return block[start:].lstrip(" :*_-–—!\n\t").rstrip("*_ \n")


def parse_story(summary: str) -> dict:
    """Split the agent's Markdown into the newsletter's sections."""
    lines = summary.strip().splitlines()
    title = lines.pop(0).lstrip("#").strip() if lines and lines[0].startswith("#") else ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", "\n".join(lines)) if b.strip()]

    hook, body, sources = "", [], []
    callouts = {"the lesson": ""}  # sections shown in their own box
    in_sources = False
    callout_waiting = None  # a callout heading on its own; its text is the next block
    lesson_at = None  # how many body blocks came before the lesson
    for block in blocks:
        if callout_waiting:
            callouts[callout_waiting] = block
            callout_waiting = None
            continue

        first_word = re.sub(r"^[^\w]+", "", block).lower()  # ignore leading #, *, emoji
        if first_word.startswith("source"):
            in_sources = True
            block = block.split("\n", 1)[1] if "\n" in block else ""
        if in_sources:
            for line in block.splitlines():
                item = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
                if item:
                    sources.append(item)
            continue

        label = next((name for name in callouts if first_word.startswith(name)), None)
        if label == "the lesson":
            lesson_at = len(body)
        if label:
            text = _strip_label(block, label)
            if text:
                callouts[label] = text
            else:
                callout_waiting = label
        elif not hook and not body and not block.startswith(("#", "-", "*", "1.")):
            hook = block
        else:
            body.append(block)

    return {"title": title, "hook": hook, "body": body, "lesson": callouts["the lesson"], "lesson_at": lesson_at, "sources": sources}


def _plain(text: str) -> str:
    """Markdown -> plain text, for the inbox preview line."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[*_`#>]", "", text).strip()


def _stat_cell(label: str, value: str, detail: str, value_color: str = INK) -> str:
    return f"""
            <td width="50%" valign="top" style="padding:6px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
                <td bgcolor="#FAF8F3" style="background:#FAF8F3;border:1px solid #ECE7DC;border-radius:12px;padding:14px 16px;">
                  <p style="margin:0;font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:{MUTED};">{label}</p>
                  <p style="margin:6px 0 0;font-family:{SANS};font-size:22px;line-height:1.2;font-weight:700;color:{value_color};">{value}</p>
                  <p style="margin:4px 0 0;font-family:{SANS};font-size:12px;line-height:1.4;color:{MUTED};">{detail}</p>
                </td>
              </tr></table>
            </td>"""


def _stats_grid(stock: dict) -> str:
    """2x2 grid of the move's key numbers. These come straight from the market data,
    never from the AI-written story."""
    up = stock["direction"] == "up"
    arrow, color = ("&#9650;", UP_COLOR) if up else ("&#9660;", DOWN_COLOR)
    volume_ratio = stock.get("volume_vs_average")
    shares = stock.get("volume") or 0
    cells = [
        _stat_cell("Closing price", f"${stock['price']:,.2f}", f"from ${stock['previous_close']:,.2f}"),
        _stat_cell("One-day move", f"{arrow} {abs(stock['change_percent']):.1f}%",
                   f"{'+' if up else '&minus;'}${abs(stock['change_amount']):,.2f} a share", color),
        _stat_cell("Company size", _money(stock.get("market_cap")), "market value"),
        _stat_cell("Trading volume", f"{volume_ratio}&times;" if volume_ratio else f"{shares / 1e6:.1f}M",
                   f"normal volume ({shares / 1e6:.1f}M shares)" if volume_ratio else "shares traded"),
    ]
    return f"""
      <tr><td class="px" style="padding:22px 34px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>{cells[0]}{cells[1]}</tr>
          <tr>{cells[2]}{cells[3]}</tr>
        </table>
      </td></tr>"""


def _also_moving(stock: dict, others: list[dict], pick_reason: Optional[str], theme: dict) -> str:
    """The other big movers that were considered, plus why today's stock was picked."""
    esc = html.escape
    rows = ""
    for o in others:
        up = o["direction"] == "up"
        arrow, color = ("&#9650;", UP_COLOR) if up else ("&#9660;", DOWN_COLOR)
        rows += f"""
          <tr>
            <td style="padding:8px 0;border-top:1px solid #ECE7DC;font-family:{SANS};font-size:14px;color:{INK};">
              <strong style="color:{INK};">{esc(o['ticker'])}</strong>
              <span style="color:{MUTED};">&nbsp;{esc(o.get('company_name') or '')}</span>
            </td>
            <td align="right" style="padding:8px 0;border-top:1px solid #ECE7DC;font-family:{SANS};font-size:14px;font-weight:700;color:{color};white-space:nowrap;">
              {arrow} {abs(o['change_percent']):.1f}%
            </td>
          </tr>"""
    reason = ""
    if pick_reason:
        reason = (f'<p style="margin:0 0 12px;font-family:{SANS};font-size:14px;line-height:1.55;color:{TEXT};">'
                  f'<strong style="color:{INK};">Why {esc(stock["ticker"])} today:</strong> {esc(pick_reason)}</p>')
    return f"""
      <tr><td class="px" style="padding:28px 40px 0;">
        <p style="margin:0 0 10px;font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{theme['deep']};">Also on the move</p>
        {reason}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}
        </table>
      </td></tr>"""


def _callout(icon: str, label: str, text: str, theme: dict, border_style: str) -> str:
    """A highlighted box, used for 'The lesson'."""
    return f"""
      <tr><td class="px" style="padding:12px 40px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
          <td bgcolor="{theme['tint']}" style="background:{theme['tint']};border-radius:14px;padding:22px 24px;border:2px {border_style} {theme['accent']};">
            <p style="margin:0 0 8px;font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{theme['deep']};">{icon}&nbsp; {label}</p>
            {_styled(_md(text), theme, size=17, color=INK).replace('margin:0 0 16px', 'margin:0')}
          </td>
        </tr></table>
      </td></tr>"""


def render_newsletter(category: str, summary: str, image: Optional[dict],
                      issue_date: Optional[datetime.date] = None,
                      stock: Optional[dict] = None,
                      others: Optional[list[dict]] = None,
                      pick_reason: Optional[str] = None) -> str:
    """Return the complete HTML email for one issue.

    `category` is the label in the pill (e.g. "LKQ · Auto - Parts"). Pass `stock`
    (a mover from market_data) to show its logo, the numbers grid and red/green colors.
    `others` are the other movers considered and `pick_reason` why `stock` was chosen."""
    theme = pick_theme(category, stock["direction"] if stock else None)
    story = parse_story(summary)
    d = issue_date or datetime.date.today()
    date_label = f"{d:%A}, {d:%B} {d.day}, {d.year}"
    esc = html.escape
    title = story["title"] or category

    sections = []

    # Logo + category pill + title + hook
    logo_cell = ""
    if stock and stock.get("logo_url"):
        logo_cell = f"""
          <td style="padding-right:12px;">
            <img src="{esc(stock['logo_url'])}" alt="{esc(stock.get('company_name') or '')} logo" width="40" height="40"
                 style="display:block;width:40px;height:40px;border:1px solid #ECE7DC;border-radius:10px;background:#FFFFFF;">
          </td>"""
    sections.append(f"""
      <tr><td class="px" style="padding:32px 40px 0;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{logo_cell}
          <td bgcolor="{theme['tint']}" style="background:{theme['tint']};border-radius:999px;padding:7px 16px;font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{theme['deep']};">
            &#9679;&nbsp; {esc(category)}
          </td>
        </tr></table>
        <h1 class="title" style="margin:18px 0 0;font-family:{SERIF};font-size:34px;line-height:1.2;font-weight:700;color:{INK};">{esc(title)}</h1>
      </td></tr>""")

    if story["hook"]:
        sections.append(f"""
      <tr><td class="px" style="padding:18px 40px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
          <td width="4" bgcolor="{theme['accent']}" style="background:{theme['accent']};border-radius:4px;font-size:0;line-height:0;">&nbsp;</td>
          <td style="padding:2px 0 2px 16px;font-family:{SERIF};font-size:20px;line-height:1.5;font-style:italic;color:{theme['deep']};">
            {_styled(_md(story['hook']), theme, size=20, color=theme['deep']).replace('<p style="', '<p style="font-family:' + SERIF + ';margin:0;' )}
          </td>
        </tr></table>
      </td></tr>""")

    if stock:
        sections.append(_stats_grid(stock))

    if image:
        caption = esc(image.get("caption", ""))
        credit = esc(image.get("credit", ""))
        sections.append(f"""
      <tr><td class="px" style="padding:28px 40px 0;">
        <img src="{esc(image['url'])}" alt="{caption}" width="520"
             style="display:block;width:100%;max-width:520px;height:auto;border:0;border-radius:14px;">
        <p style="margin:10px 0 0;font-family:{SANS};font-size:13px;line-height:1.5;color:{MUTED};">
          {caption}{f'<br><span style="font-size:11px;">Photo: {credit}</span>' if credit else ''}
        </p>
      </td></tr>""")

    # Body, with the lesson box placed where it appeared in the story.
    split = story["lesson_at"] if story["lesson_at"] is not None else len(story["body"])
    for i, blocks in enumerate((story["body"][:split], story["body"][split:])):
        if blocks:
            body_html = "".join(_styled(_md(b), theme) for b in blocks)
            sections.append(f"""
      <tr><td class="px" style="padding:{28 if i == 0 else 20}px 40px 0;">{body_html}</td></tr>""")
        if i == 0 and story["lesson"]:
            sections.append(_callout("&#127891;", "The lesson", story["lesson"], theme, "solid"))

    if stock and others:
        sections.append(_also_moving(stock, others, pick_reason, theme))

    if story["sources"]:
        items = "".join(
            f'<li style="margin:0 0 4px;word-break:break-word;">{_styled(_md(s), theme, size=13, color=MUTED).replace("<p style=", "<span style=").replace("</p>", "</span>").replace("margin:0 0 16px;", "")}</li>'
            for s in story["sources"]
        )
        sections.append(f"""
      <tr><td class="px" style="padding:28px 40px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr><td style="border-top:1px solid #E6E2D8;font-size:0;line-height:0;">&nbsp;</td></tr>
        </table>
        <p style="margin:20px 0 8px;font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{MUTED};">Sources</p>
        <ul style="margin:0;padding-left:18px;font-family:{SANS};font-size:13px;line-height:1.5;color:{MUTED};">{items}</ul>
      </td></tr>""")

    preheader = esc(_plain(story["hook"]) or title)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{esc(title)}</title>
<style>
  @media (max-width: 620px) {{
    .px {{ padding-left: 22px !important; padding-right: 22px !important; }}
    .title {{ font-size: 28px !important; }}
    .masthead {{ font-size: 28px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{PAPER};">
  <!-- Inbox preview text (hidden in the email itself) -->
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}&#8203;&nbsp;&#8203;&nbsp;&#8203;&nbsp;</div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAPER}" style="background:{PAPER};">
    <tr><td align="center" style="padding:32px 12px;">

      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">

        <!-- Masthead -->
        <tr><td bgcolor="{theme['deep']}" style="background:{theme['deep']};background-image:linear-gradient(135deg,{theme['deep']} 0%,{theme['accent']} 100%);border-radius:20px 20px 0 0;padding:34px 40px 30px;" class="px">
          <p style="margin:0 0 10px;font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#FFFFFF;opacity:0.85;">{esc(date_label)}</p>
          <p class="masthead" style="margin:0;font-family:{SERIF};font-size:36px;line-height:1.1;font-weight:700;color:#FFFFFF;">{esc(NEWSLETTER_NAME)}</p>
          <p style="margin:10px 0 0;font-family:{SANS};font-size:15px;line-height:1.4;color:#FFFFFF;opacity:0.9;">{esc(TAGLINE)}</p>
        </td></tr>

        <!-- Color stripe -->
        <tr><td style="font-size:0;line-height:0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
            <td height="6" width="33%" bgcolor="{theme['accent']}" style="background:{theme['accent']};font-size:0;line-height:0;">&nbsp;</td>
            <td height="6" width="34%" bgcolor="#FFD166" style="background:#FFD166;font-size:0;line-height:0;">&nbsp;</td>
            <td height="6" width="33%" bgcolor="{INK}" style="background:{INK};font-size:0;line-height:0;">&nbsp;</td>
          </tr></table>
        </td></tr>

        <!-- Story card -->
        <tr><td bgcolor="#FFFFFF" style="background:#FFFFFF;padding:0 0 36px;word-break:break-word;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            {"".join(sections)}
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td bgcolor="{INK}" style="background:{INK};border-radius:0 0 20px 20px;padding:26px 40px;text-align:center;" class="px">
          <p style="margin:0;font-family:{SERIF};font-size:18px;font-weight:700;color:#FFFFFF;">{esc(NEWSLETTER_NAME)}</p>
          <p style="margin:8px 0 0;font-family:{SANS};font-size:13px;line-height:1.5;color:#B8B9D0;">
            Researched and written by an AI agent. Stay curious &#10024;
          </p>
          <p style="margin:10px 0 0;font-family:{SANS};font-size:11px;line-height:1.5;color:#8C8DA8;">{esc(DISCLAIMER)}</p>
        </td></tr>

      </table>

    </td></tr>
  </table>
</body>
</html>"""


if __name__ == "__main__":
    # Sample issue about a made-up company, for checking the design without API calls.
    sample = """# Acme Robotics Drops 18% After Cutting Its Forecast

Record sales weren't enough: investors only cared about what Acme said comes next.

## What happened
Acme Robotics reported quarterly revenue of $2.1 billion, slightly above what analysts expected. But it also lowered its **guidance** (the company's own forecast for future sales) for next year, blaming slower orders from car makers.

## Why the market cared
A stock price reflects what investors expect a company to earn in the *future*, not what it earned last quarter. A beat on old numbers matters less than a cut to the forecast, because the forecast is what changes the estimate of future profits.

## The lesson
Markets look forward. A company can beat expectations and still fall if it lowers its outlook, because guidance resets what investors think the next few years look like.

## What to watch next
Whether other robotics suppliers report the same slowdown, and Acme's investor day in March.

## Sources
- https://www.example.com/acme-earnings
- [Acme Q3 results (example)](https://www.example.com/acme-q3)
"""
    stock = {
        "ticker": "ACME", "company_name": "Acme Robotics", "price": 41.20, "previous_close": 50.24,
        "change_amount": -9.04, "change_percent": -18.0, "direction": "down",
        "market_cap": 8_400_000_000, "volume": 21_300_000, "volume_vs_average": 5.6, "logo_url": None,
    }
    with open("preview.html", "w", encoding="utf-8") as f:
        f.write(render_newsletter("ACME · Industrial Machinery", sample, None, stock=stock))
    print("Wrote preview.html")
