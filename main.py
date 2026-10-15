import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from typing import Dict
from pydantic import BaseModel, Field
import resend

load_dotenv()

from agent import research_topic

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


@app.get("/topic")
def random_topic(category: str = "science") -> dict[str, str]:
    return {"category": category, "summary": research_topic(category)}


@app.post("/")
def send_mail() -> Dict:
    params: resend.Emails.SendParams = {
        "from": "Acme <onboarding@resend.dev>",
        "to": ["azamjb123@gmail.com"],
        "subject": "hello world",
        "html": "<strong>it works!</strong>",
    }
    email: resend.Emails.SendResponse = resend.Emails.send(params)
    return email


@app.put("/items/{item_id}", response_model=Item)
def update_item(item_id: int, item_data: ItemCreate) -> Item:
    if item_id not in items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    item = Item(id=item_id, **item_data.model_dump())
    items[item_id] = item
    return item

