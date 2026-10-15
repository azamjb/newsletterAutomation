# Simple Items API

A small FastAPI service with a health check and in-memory CRUD endpoints for items. Data is kept in process memory, so it resets whenever the server restarts.

## Setup

Use Python 3.10 or newer. Create and activate a virtual environment, then install dependencies:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```sh
fastapi dev main.py
```

The API runs locally at `http://127.0.0.1:8000`. Interactive API documentation is available at `/docs` and `/redoc`.

## Endpoints

- `GET /health` — service health status
- `GET /items` — list all items
- `POST /items` — create an item; JSON body: `{"name": "Notebook", "description": "A lined notebook"}`
- `GET /items/{item_id}` — retrieve one item
- `PUT /items/{item_id}` — replace an item's name and description
- `DELETE /items/{item_id}` — delete an item

Example create request:

```sh
curl -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"name":"Notebook","description":"A lined notebook"}'
```

## Test

```sh
pytest
```
