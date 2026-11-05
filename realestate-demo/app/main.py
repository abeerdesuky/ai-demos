"""
تشغيل:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import csv
import json
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

from .bot import BY_ID, INFO, LISTINGS, answer, card, describe_filters, fmt_price, parse_query, search

ROOT = Path(__file__).resolve().parent.parent
LEADS = ROOT / "data" / "leads.csv"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "demo123")

app = FastAPI(title=INFO["name"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.filters["price"] = fmt_price

_hits: dict[str, deque] = defaultdict(deque)


def _rate_limit(request: Request, limit: int = 30, window: int = 60, bucket: str = "api"):
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


TIMELINES = {"فورًا (خلال شهر)": 3, "خلال 3 شهور": 2, "خلال سنة": 1, "بستكشف بس": 0}
PAYMENTS = {"كاش": 2, "تقسيط": 1, "تمويل عقاري": 1, "إيجار": 1}


class LeadIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    phone: str = Field(..., max_length=20)
    listing_id: str = Field("", max_length=10)
    budget: int = Field(0, ge=0, le=500_000_000)
    timeline: str = Field(..., max_length=30)
    payment: str = Field(..., max_length=30)
    notes: str = Field("", max_length=300)
    source: str = Field("form", max_length=10)


def score_lead(lead: LeadIn) -> tuple[int, str]:
    """Simple, explainable lead scoring so sales calls the hottest leads first."""
    pts = TIMELINES.get(lead.timeline, 0) + PAYMENTS.get(lead.payment, 0)
    l = BY_ID.get(lead.listing_id)
    if l:
        pts += 1
        if lead.budget and lead.budget >= l["price"] * 0.9:
            pts += 2
    elif lead.budget:
        pts += 1
    return pts, ("🔥 ساخن" if pts >= 7 else "🌤️ مهتم" if pts >= 3 else "❄️ بارد")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    data = [{**card(l), "purpose": l["purpose"], "raw_price": l["price"], "baths": l["baths"],
             "compound": l["compound"], "finishing": l["finishing"], "features": l["features"],
             "delivery": l["delivery"], "installment": l["installment"], "desc": l["desc"]} for l in LISTINGS]
    return templates.TemplateResponse(request, "index.html", {
        "c": INFO, "listings": LISTINGS, "data_json": json.dumps(data, ensure_ascii=False),
        "types": sorted({l["type"] for l in LISTINGS}), "timelines": list(TIMELINES), "payments": list(PAYMENTS)})


@app.get("/api/search")
def api_search(request: Request, q: str = ""):
    _rate_limit(request)
    f = parse_query(q[:300])
    if not f:
        return {"filters": {}, "desc": "", "ids": [l["id"] for l in LISTINGS], "relaxed": []}
    res, relaxed = search(f, limit=50)
    return {"filters": f, "desc": describe_filters(f), "ids": [l["id"] for l in res], "relaxed": relaxed}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    _rate_limit(request, limit=20, bucket="chat")
    return answer(body.message, body.history)


@app.post("/api/lead")
def lead(body: LeadIn, request: Request):
    _rate_limit(request, limit=5, bucket="form")
    phone = re.sub(r"\D", "", body.phone)
    if not re.fullmatch(r"(20)?0?1[0125]\d{8}", phone):
        raise HTTPException(400, "رقم الموبايل مش صحيح")
    if body.listing_id and body.listing_id not in BY_ID:
        raise HTTPException(400, "الوحدة مش موجودة")
    pts, label = score_lead(body)
    l = BY_ID.get(body.listing_id)
    row = {"created_at": datetime.now().isoformat(timespec="minutes"), "score": pts, "label": label,
           "name": body.name.strip(), "phone": phone,
           "listing": f"{l['id']} - {l['title']}" if l else "", "budget": body.budget,
           "timeline": body.timeline, "payment": body.payment, "notes": body.notes.strip(), "source": body.source}
    new = not LEADS.exists()
    with LEADS.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    return {"ok": True, "message": f"شكرًا يا {body.name.split()[0]} ✅ مستشار عقاري هيكلمك خلال ساعة عمل."}


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, token: str = ""):
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")
    rows = []
    if LEADS.exists():
        with LEADS.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (int(r["score"]), r["created_at"]), reverse=True)
    counts = {k: sum(1 for r in rows if r["label"] == k) for k in ("🔥 ساخن", "🌤️ مهتم", "❄️ بارد")}
    return templates.TemplateResponse(request, "admin.html", {"c": INFO, "rows": rows, "counts": counts})
