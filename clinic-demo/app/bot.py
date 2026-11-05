"""
محرك الشات بوت: بيرد على الأسئلة من بيانات النشاط (data/clinic.json).

وضعين:
- لو فيه LLM_API_KEY: بيجيب أقرب معلومات من البيانات (RAG) ويبعتها لأي API متوافق مع OpenAI
  (OpenAI / Groq / OpenRouter / DeepSeek ...) عشان يكتب رد طبيعي.
- لو مفيش مفتاح: بيرد مباشرة من أقرب معلومة في البيانات (مناسب للديمو ومجاني).
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "clinic.json"

# ---------- Arabic text normalization ----------
_DIACRITICS = re.compile(r"[ؗ-ًؚ-ْـ]")


def normalize(text: str) -> str:
    text = _DIACRITICS.sub("", text.lower())
    text = re.sub("[إأآا]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Common words that add noise to matching
_STOP = {normalize(w) for w in (
    "هل في فيه عندكم عندك انا أنا ممكن عايز عاوز عايزة اعرف أعرف ايه إيه "
    "من على عن الى إلى ده دي دا اللي هو هي يا لو بس و او أو مع كده انتو انتم"
).split()}


def _tokens(text: str) -> list[str]:
    return [w for w in normalize(text).split() if w not in _STOP]


def _vector(text: str) -> Counter:
    """Character n-grams (2-4) per word: robust to Arabic prefixes like ال/بال/وال."""
    vec: Counter = Counter()
    for w in _tokens(text):
        w = re.sub(r"^(وال|بال|فال|كال|لل|ال)", "", w) or w
        padded = f" {w} "
        for n in (2, 3, 4):
            for i in range(len(padded) - n + 1):
                vec[padded[i:i + n]] += 1
    return vec


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


# ---------- Knowledge base ----------
@dataclass
class Chunk:
    key: str       # text used for matching
    answer: str    # direct answer (fallback mode)
    context: str   # fact sent to the LLM
    kind: str = "info"
    vec: Counter = None


def load_kb(path: Path = DATA_FILE) -> tuple[dict, list[Chunk]]:
    info = json.loads(path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []

    def add(key, answer, context=None, kind="info"):
        chunks.append(Chunk(key, answer, context or answer, kind))

    for s in info["services"]:
        ans = f"{s['name']}: {s['desc']} السعر {s['price']}."
        add(f"{s['name']} سعر تكلفة بكام {s['desc']}", ans, kind="service")
    prices = "، ".join(f"{s['name']} ({s['price']})" for s in info["services"])
    add("الاسعار الخدمات قائمة بكام الكشف تكلفة", f"دي أسعار خدماتنا: {prices}.")
    for d in info["doctors"]:
        add(f"{d['name']} دكتور {d['title']} مواعيد ايام",
            f"{d['name']} - {d['title']}، متواجد {d['days']}.")
    docs = "، ".join(f"{d['name']} ({d['title']})" for d in info["doctors"])
    add("الدكاتره الاطباء مين الدكتور", f"أطباء العيادة: {docs}.")
    for f in info["faq"]:
        add(f"{f['q']} {f.get('tags', '')}", f["a"], f"س: {f['q']} ج: {f['a']}")
    add("مواعيد العياده الساعه بتفتحوا بتقفلوا شغالين امتى اجازه",
        f"مواعيد العيادة: {info['hours']}.")
    add("العنوان المكان فين اللوكيشن", f"العنوان: {info['address']}.")
    add("رقم التليفون واتساب تواصل اتصل",
        f"تقدر تكلمنا على {info['phone']} أو على الواتساب بنفس الرقم.")

    for c in chunks:
        c.vec = _vector(c.key)
    return info, chunks


INFO, CHUNKS = load_kb()

# ---------- Intents ----------
def _alts(words: str) -> str:
    return "|".join(normalize(w) for w in words.split())


_BOOK = re.compile(_alts("احجز حجز احجزلي ميعاد معاد موعد book appointment"))
_GREET = re.compile(r"^(" + _alts("السلام سلام اهلا أهلا هاي هلو صباح مساء hi hello") + r")")
_THANKS = re.compile(_alts("شكرا متشكر تسلم thanks thank"))
_PRICE = re.compile(_alts("سعر بكام تكلفه تكلف كام اسعار"))

SUGGESTIONS = ["الأسعار", "مواعيد العيادة", "فيه تقسيط؟", "عايز أحجز"]


def retrieve(query: str, k: int = 4) -> list[tuple[float, Chunk]]:
    q = _vector(query)
    boost = 1.6 if _PRICE.search(normalize(query)) else 1.0
    scored = sorted(((_cosine(q, c.vec) * (boost if c.kind == "service" else 1.0), c) for c in CHUNKS),
                    key=lambda x: x[0], reverse=True)
    return scored[:k]


# ---------- LLM (optional) ----------
def _llm_config():
    key = os.getenv("LLM_API_KEY")
    if not key:
        return None
    return {
        "key": key,
        "url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
    }


def _system_prompt(facts: str) -> str:
    return (
        f"أنت موظف خدمة العملاء في {INFO['name']}. رد باللهجة المصرية بشكل ودود ومختصر (جملتين أو تلاتة).\n"
        "اعتمد فقط على المعلومات دي، ولو السؤال مش موجود فيها قول إنك هتوصله للعيادة واطلب يكلمنا واتساب. "
        "ممنوع تدي تشخيص طبي أو تقترح أدوية؛ انصح بالكشف.\n"
        "لو العميل عايز يحجز شجعه يضغط زر الحجز.\n\n"
        f"معلومات العيادة:\n{facts}\n"
        f"المواعيد: {INFO['hours']} | العنوان: {INFO['address']} | التليفون: {INFO['phone']}"
    )


def _call_llm(cfg: dict, message: str, history: list[dict], facts: str) -> str:
    msgs = [{"role": "system", "content": _system_prompt(facts)}]
    for h in history[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:1000]})
    msgs.append({"role": "user", "content": message})
    req = urllib.request.Request(
        cfg["url"],
        data=json.dumps({"model": cfg["model"], "messages": msgs, "temperature": 0.3,
                         "max_tokens": 300}).encode(),
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()


# ---------- Main entry ----------
def answer(message: str, history: list[dict] | None = None) -> dict:
    message = (message or "").strip()[:500]
    history = history or []
    norm = normalize(message)
    if not norm:
        return {"reply": "اكتبلي سؤالك وأنا معاك 🙂", "suggestions": SUGGESTIONS}

    wants_booking = bool(_BOOK.search(norm))
    hits = retrieve(message)
    action = "book" if wants_booking else None

    cfg = _llm_config()
    if cfg:
        try:
            facts = "\n".join(c.context for s, c in hits if s > 0.05)
            reply = _call_llm(cfg, message, history, facts)
            return {"reply": reply, "action": action, "suggestions": SUGGESTIONS, "mode": "llm"}
        except Exception as e:  # fall back to retrieval if the API fails
            print("LLM error, falling back:", e)

    if wants_booking:
        reply = "تمام! اضغط على زر «احجز الآن» تحت واكتب اسمك ورقمك، وهنكلمك نأكد المعاد 👇"
    elif _GREET.search(norm) and len(norm.split()) <= 3:
        reply = f"أهلاً بيك في {INFO['name']} 👋 تحب تعرف إيه؟ الأسعار، المواعيد، ولا تحجز؟"
    elif _THANKS.search(norm):
        reply = "العفو! لو احتجت أي حاجة تانية أنا موجود 🦷"
    elif hits and hits[0][0] >= 0.18:
        reply = hits[0][1].answer
    else:
        reply = ("مش متأكد من الإجابة دي 🙏 ممكن تكلمنا واتساب على "
                 f"{INFO['phone']} وحد من العيادة هيرد عليك.")
    return {"reply": reply, "action": action, "suggestions": SUGGESTIONS, "mode": "local"}
