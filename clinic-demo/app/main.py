"""
تشغيل:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import csv
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .bot import INFO, answer

ROOT = Path(__file__).resolve().parent.parent
BOOKINGS = ROOT / "data" / "bookings.csv"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "demo123")

app = FastAPI(title=INFO["name"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")

# --- simple in-memory rate limit (per IP) ---
_hits: dict[str, deque] = defaultdict(deque)


def _rate_limit(request: Request, limit: int = 20, window: int = 60, bucket: str = "chat"):
    ip = request.client.host if request.client else "?"
    q, now = _hits[f"{bucket}:{ip}"], time.time()  # separate counters per endpoint
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "كتير شوية 😅 استنى دقيقة وجرب تاني")
    q.append(now)


class ChatIn(BaseModel):
    message: str = Field(..., max_length=500)
    history: list[dict] = []


class BookingIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    phone: str = Field(..., max_length=20)
    service: str = Field("", max_length=60)
    date: str = Field("", max_length=20)
    notes: str = Field("", max_length=300)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"c": INFO})


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    _rate_limit(request)
    return answer(body.message, body.history)


@app.post("/api/book")
def book(body: BookingIn, request: Request):
    _rate_limit(request, limit=5, bucket="form")
    phone = re.sub(r"\D", "", body.phone)
    if not re.fullmatch(r"(20)?0?1[0125]\d{8}", phone):
        raise HTTPException(400, "رقم الموبايل مش صحيح")
    new = not BOOKINGS.exists()
    with BOOKINGS.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["created_at", "name", "phone", "service", "date", "notes"])
        w.writerow([datetime.now().isoformat(timespec="minutes"), body.name.strip(), phone,
                    body.service, body.date, body.notes.strip()])
    return {"ok": True, "message": f"تم استلام طلبك يا {body.name.split()[0]} ✅ هنكلمك قريب نأكد المعاد."}


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, token: str = ""):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")
    rows = []
    if BOOKINGS.exists():
        with BOOKINGS.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))[::-1]
    return templates.TemplateResponse(request, "admin.html", {"c": INFO, "rows": rows})
