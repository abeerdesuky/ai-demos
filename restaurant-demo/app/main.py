"""
تشغيل:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.parse
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
ORDERS = ROOT / "data" / "orders.csv"
RESERVATIONS = ROOT / "data" / "reservations.csv"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "demo123")
ITEMS = {it["id"]: it for cat in INFO["menu"] for it in cat["items"]}
FEE, FREE_OVER, MIN_ORDER = 25, 500, 150

app = FastAPI(title=INFO["name"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")

_hits: dict[str, deque] = defaultdict(deque)


def _rate_limit(request: Request, limit: int = 20, window: int = 60, bucket: str = "chat"):
    ip = request.client.host if request.client else "?"
    q, now = _hits[f"{bucket}:{ip}"], time.time()  # separate counters per endpoint
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "كتير شوية 😅 استنى دقيقة وجرب تاني")
    q.append(now)


def _phone(raw: str) -> str:
    phone = re.sub(r"\D", "", raw)
    if not re.fullmatch(r"(20)?0?1[0125]\d{8}", phone):
        raise HTTPException(400, "رقم الموبايل مش صحيح")
    return phone


def _append(path: Path, row: dict):
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))[::-1]


class ChatIn(BaseModel):
    message: str = Field(..., max_length=500)
    history: list[dict] = []


class OrderIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    phone: str = Field(..., max_length=20)
    address: str = Field(..., min_length=5, max_length=200)
    items: dict[str, int]          # {item_id: qty}
    notes: str = Field("", max_length=300)


class ReserveIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    phone: str = Field(..., max_length=20)
    guests: int = Field(..., ge=1, le=40)
    date: str = Field(..., max_length=20)
    time: str = Field(..., max_length=10)
    notes: str = Field("", max_length=300)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    menu_json = json.dumps({k: {"name": v["name"], "price": v["price"]} for k, v in ITEMS.items()},
                           ensure_ascii=False)
    return templates.TemplateResponse(request, "index.html", {
        "c": INFO, "menu_json": menu_json, "fee": FEE, "free_over": FREE_OVER, "min_order": MIN_ORDER})


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    _rate_limit(request)
    return answer(body.message, body.history)


@app.post("/api/order")
def order(body: OrderIn, request: Request):
    _rate_limit(request, limit=5, bucket="form")
    phone = _phone(body.phone)
    lines, subtotal = [], 0
    for item_id, qty in body.items.items():
        if item_id not in ITEMS or not 1 <= qty <= 20:
            raise HTTPException(400, "فيه صنف مش صحيح في السلة")
        it = ITEMS[item_id]
        subtotal += it["price"] * qty   # prices are always computed on the server
        lines.append(f"• {qty} × {it['name']} = {it['price'] * qty} ج")
    if subtotal < MIN_ORDER:
        raise HTTPException(400, f"الحد الأدنى للطلب {MIN_ORDER} جنيه")
    fee = 0 if subtotal >= FREE_OVER else FEE
    total = subtotal + fee

    text = "\n".join([f"🛒 أوردر جديد - {INFO['name']}", *lines,
                      f"التوصيل: {fee} ج", f"الإجمالي: {total} ج", "",
                      f"الاسم: {body.name}", f"الموبايل: {phone}", f"العنوان: {body.address}"]
                     + ([f"ملاحظات: {body.notes}"] if body.notes else []))
    _append(ORDERS, {"created_at": datetime.now().isoformat(timespec="minutes"), "name": body.name,
                     "phone": phone, "address": body.address, "items": " | ".join(lines),
                     "total": total, "notes": body.notes})
    return {"ok": True, "total": total,
            "whatsapp_url": f"https://wa.me/{INFO['whatsapp']}?text={urllib.parse.quote(text)}"}


@app.post("/api/reserve")
def reserve(body: ReserveIn, request: Request):
    _rate_limit(request, limit=5, bucket="form")
    phone = _phone(body.phone)
    _append(RESERVATIONS, {"created_at": datetime.now().isoformat(timespec="minutes"), "name": body.name,
                           "phone": phone, "guests": body.guests, "date": body.date, "time": body.time,
                           "notes": body.notes})
    return {"ok": True, "message": f"تم استلام حجزك يا {body.name.split()[0]} لـ {body.guests} أفراد ✅ هنأكدلك على الموبايل."}


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, token: str = ""):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")
    return templates.TemplateResponse(request, "admin.html", {
        "c": INFO, "orders": _read(ORDERS), "reservations": _read(RESERVATIONS)})
