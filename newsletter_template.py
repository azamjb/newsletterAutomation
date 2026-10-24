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

NEWSLETTER_NAME = "The Curiosity Dispatch"
TAGLINE = "One random rabbit hole, delivered to your inbox."

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


def pick_theme(category: str) -> dict:
    index = int(hashlib.md5(category.encode()).hexdigest(), 16) % len(THEMES)
    return THEMES[index]


def _styled(fragment: str, theme: dict, size: int = 16, color: str = TEXT) -> str:
    """Add inline styles to the plain tags the markdown library produces."""
    p = f"margin:0 0 16px;font-family:{SANS};font-size:{size}px;line-height:1.65;color:{color};"
    rules = {
        "<p>": f'<p style="{p}">',
        "<ul>": f'<ul style="margin:0 0 16px;padding-left:22px;">',
        "<ol>": f'<ol style="margin:0 0 16px;padding-left:22px;">',
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

    hook, body, fun_fact, sources = "", [], "", []
    in_sources = False
    for block in blocks:
        first_word = re.sub(r"^[^\w]+", "", block).lower()  # ignore leading #, *, emoji
        if first_word.startswith("source"):
            in_sources = True
            block = block.split("\n", 1)[1] if "\n" in block else ""
        if in_sources:
            for line in block.splitlines():
                item = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
                if item:
                    sources.append(item)
        elif first_word.startswith("fun fact"):
            fun_fact = _strip_label(block, "fun fact")
        elif not hook and not body and not block.startswith(("#", "-", "*", "1.")):
            hook = block
        else:
            body.append(block)

    return {"title": title, "hook": hook, "body": body, "fun_fact": fun_fact, "sources": sources}


def _plain(text: str) -> str:
    """Markdown -> plain text, for the inbox preview line."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[*_`#>]", "", text).strip()


def render_newsletter(category: str, summary: str, image: Optional[dict],
                      issue_date: Optional[datetime.date] = None) -> str:
    """Return the complete HTML email for one issue."""
    theme = pick_theme(category)
    story = parse_story(summary)
    d = issue_date or datetime.date.today()
    date_label = f"{d:%A}, {d:%B} {d.day}, {d.year}"
    esc = html.escape
    title = story["title"] or category

    sections = []

    # Category pill + title + hook
    sections.append(f"""
      <tr><td class="px" style="padding:32px 40px 0;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
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

    if story["body"]:
        body_html = "".join(_styled(_md(b), theme) for b in story["body"])
        sections.append(f"""
      <tr><td class="px" style="padding:28px 40px 0;">{body_html}</td></tr>""")

    if story["fun_fact"]:
        sections.append(f"""
      <tr><td class="px" style="padding:12px 40px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
          <td bgcolor="{theme['tint']}" style="background:{theme['tint']};border-radius:14px;padding:22px 24px;border:2px dashed {theme['accent']};">
            <p style="margin:0 0 8px;font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{theme['deep']};">&#128161;&nbsp; Fun fact</p>
            {_styled(_md(story['fun_fact']), theme, size=17, color=INK).replace('margin:0 0 16px', 'margin:0')}
          </td>
        </tr></table>
      </td></tr>""")

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
        </td></tr>

      </table>

    </td></tr>
  </table>
</body>
</html>"""


if __name__ == "__main__":
    sample = """# The Tiny Tank That Survived Space

Meet the eight-legged, half-millimetre beast that laughs at boiling water, deep freezes and the vacuum of space.

Tardigrades, also called **water bears**, live almost everywhere: moss on your roof, Antarctic ice, deep-sea mud. Under a microscope they look like chubby gummy bears with claws.

Their party trick is *cryptobiosis*. When things get rough they dry out, curl into a "tun" and drop their metabolism to almost nothing, staying like that for years.

In 2007 the European Space Agency strapped a batch to the outside of a satellite. Most came back alive, making them the first animals known to survive open space.

**Fun fact:** Some tardigrades make a protein called Dsup that shields their DNA from radiation, and scientists have added it to human cells in the lab.

## Sources
- [Tardigrade – Wikipedia](https://en.wikipedia.org/wiki/Tardigrade)
- https://www.esa.int/Science_Exploration/Human_and_Robotic_Exploration/Research/Tardigrades
"""
    image = {
        "url": "https://upload.wikimedia.org/wikipedia/commons/6/65/Hypsibiusdujardini.jpg",
        "caption": "A water bear (Hypsibius dujardini) under the microscope.",
        "credit": "Willow Gabriel, Goldstein Lab, CC BY-SA 2.5 via Wikimedia Commons",
    }
    with open("preview.html", "w", encoding="utf-8") as f:
        f.write(render_newsletter("Tardigrades", sample, image))
    print("Wrote preview.html")
