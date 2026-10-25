import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from typing import Dict
from pydantic import BaseModel, Field
import anthropic
import resend

load_dotenv()

from agent import find_image, research_mover, select_mover
from market_data import MarketDataError, get_biggest_mover
from newsletter_template import render_newsletter

app = FastAPI(title="Simple Items API", version="1.0.0")
resend.api_key = os.environ["RESEND_API_KEY"]

class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class Item(ItemCreate):
    id: int


items: dict[int, Item] = {}
next_item_id = 1


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/mover")
def biggest_mover() -> dict:
    """The previous trading day's biggest stock move among companies worth $2B+
    (no penny stocks, warrants, ETFs or funds). `candidates` lists the top 5 that
    passed, so the newsletter can later pick the one with the clearest news story."""
    try:
        as_of, mover, candidates = get_biggest_mover()
    except MarketDataError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    if mover is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No movers passed the filters for the latest trading day")
    return {"as_of": as_of, "mover": mover, "candidates": candidates}


def generate_issue() -> dict:
    """Build today's issue: get the previous trading day's biggest movers, let Claude
    pick the one with the clearest news story, research why it moved, find a picture
    of the company, and render the email."""
    try:
        trading_day, _, candidates = get_biggest_mover()
    except MarketDataError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    if not candidates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No movers passed the filters for the latest trading day")

    print(f"Choosing from {', '.join(c['ticker'] for c in candidates)} for {trading_day}")
    selection = select_mover(candidates, trading_day)
    mover = selection["mover"]
    others = [c for c in candidates if c["ticker"] != mover["ticker"]]
    print(f"Researching {mover['ticker']} ({mover['change_percent']:+.2f}%)")

    try:
        story = research_mover(mover, trading_day, selection["notes"])
    except (anthropic.APIError, RuntimeError) as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Research agent failed: {e}")

    image = find_image(f"{mover['company_name']} ({mover['industry']})", story)
    if image is None and mover.get("logo_url"):
        image = {"url": mover["logo_url"], "caption": f"{mover['company_name']} logo", "credit": ""}

    label = f"{mover['ticker']} · {mover.get('industry') or mover.get('sector') or ''}".rstrip(" ·")
    # The story's first line is its "# Headline"; use it as the email subject.
    headline = story.splitlines()[0].lstrip("# ").strip()
    move = f"{mover['ticker']} {mover['change_percent']:+.1f}%"
    return {
        "trading_day": trading_day,
        "mover": mover,
        "pick_reason": selection["reason"],
        "considered": [{"ticker": c["ticker"], "change_percent": c["change_percent"]} for c in candidates],
        "subject": f"{move}: {headline}" if headline else f"Why {move} yesterday",
        "image": image,
        "html": render_newsletter(label, story, image, stock=mover, others=others,
                                  pick_reason=selection["reason"]),
    }


@app.get("/preview", response_class=HTMLResponse)
def preview_newsletter() -> str:
    """Generate today's full issue and show it in the browser instead of emailing it."""
    return generate_issue()["html"]


@app.post("/")
def send_mail() -> Dict:
    """Generate today's issue and email it."""
    issue = generate_issue()
    params: resend.Emails.SendParams = {
        "from": "Acme <onboarding@resend.dev>",
        "to": ["azamjb123@gmail.com"],
        "subject": issue["subject"],
        "html": issue["html"],
    }
    email: resend.Emails.SendResponse = resend.Emails.send(params)
    return {
        "ticker": issue["mover"]["ticker"],
        "trading_day": issue["trading_day"],
        "pick_reason": issue["pick_reason"],
        "considered": issue["considered"],
        "subject": issue["subject"],
        "image": issue["image"],
        "email": email,
    }


@app.put("/items/{item_id}", response_model=Item)
def update_item(item_id: int, item_data: ItemCreate) -> Item:
    if item_id not in items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    item = Item(id=item_id, **item_data.model_dump())
    items[item_id] = item
    return item

