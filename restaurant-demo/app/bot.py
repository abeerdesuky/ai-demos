"""
محرك الشات بوت: بيرد على الأسئلة من بيانات النشاط (data/restaurant.json).

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

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "restaurant.json"

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

    d = info["delivery"]
    for cat in info["menu"]:
        for it in cat["items"]:
            ans = f"{it['name']}: {it['desc']} السعر {it['price']} جنيه."
            add(f"{it['name']} {it.get('tags', '')} سعر بكام", ans, kind="item")
        lst = "، ".join(f"{it['name']} ({it['price']} ج)" for it in cat["items"])
        add(f"{cat['category']} {cat['category']} انواع", f"{cat['icon']} {cat['category']}: {lst}.", kind="item")
    cats = "، ".join(c["category"] for c in info["menu"])
    add("المنيو الاكل عندكم ايه الاصناف قائمه الطعام الاسعار",
        f"المنيو فيه: {cats}. تقدر تشوف كل الأصناف بالأسعار في قسم المنيو، أو اسألني عن أي صنف.")
    top = [it for c in info["menu"] for it in c["items"] if "مشهور" in it.get("tags", "")]
    if top:
        add("ترشحلي ترشح تنصحني احسن حاجه اطلب ايه مشهور الاكثر طلبا جديد",
            "أنصحك بـ " + "، و".join(f"{t['name']} ({t['price']} ج)" for t in top)
            + " — ده الأكثر طلبًا عندنا 🔥. ولو معاك عيلة جرّب طاجن المشكل.")
    for f in info["faq"]:
        add(f"{f['q']} {f.get('tags', '')}", f["a"], f"س: {f['q']} ج: {f['a']}")
    add("مواعيد المطعم الساعه بتفتحوا بتقفلوا شغالين امتى", f"مواعيدنا: {info['hours']}.")
    add("العنوان المكان فين اللوكيشن الفرع", f"العنوان: {info['address']}.")
    add("رقم التليفون واتساب تواصل اتصل", f"تقدر تكلمنا على {info['phone']} أو واتساب بنفس الرقم.")
    add("الحد الادني للطلب مينيمم اقل طلب", f"الحد الأدنى للطلب {d['min_order']}، والتوصيل {d['fee']}.")
    add("مصاريف التوصيل الدليفري بكام وقت التوصيل بياخد قد ايه",
        f"التوصيل {d['fee']}، وبيوصل في {d['time']}. بنوصّل لـ {d['areas']}.")

    for c in chunks:
        c.vec = _vector(c.key)
    return info, chunks


INFO, CHUNKS = load_kb()

# ---------- Intents ----------
def _alts(words: str) -> str:
    return "|".join(normalize(w) for w in words.split())


_BOOK = re.compile(_alts("احجز حجز احجزلي ترابيزه طاوله reserve"))
_ORDER = re.compile(_alts("اطلب اوردر order"))
_GREET = re.compile(r"^(" + _alts("السلام سلام اهلا أهلا هاي هلو صباح مساء hi hello") + r")")
_THANKS = re.compile(_alts("شكرا متشكر تسلم thanks thank"))
_PRICE = re.compile(_alts("سعر بكام تكلفه تكلف كام اسعار"))

SUGGESTIONS = ["ترشحلي إيه؟", "المنيو", "فيه توصيل؟", "عندكم نباتي؟", "احجز ترابيزة"]


def retrieve(query: str, k: int = 4) -> list[tuple[float, Chunk]]:
    q = _vector(query)
    boost = 1.6 if _PRICE.search(normalize(query)) else 1.0
    scored = sorted(((_cosine(q, c.vec) * (boost if c.kind == "item" else 1.0), c) for c in CHUNKS),
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
        f"أنت موظف خدمة العملاء في {INFO['name']}. رد باللهجة المصرية بشكل ودود وخفيف ومختصر (جملتين أو تلاتة).\n"
        "اعتمد فقط على المعلومات دي، وماتخترعش أصناف أو أسعار مش موجودة. لو السؤال مش موجود قول إنك هتوصله للمطعم واطلب يكلمنا واتساب.\n"
        "لو العميل محتار رشّحله أصناف مناسبة من المعلومات. لو عايز يطلب قوله يضيف الأصناف للسلة من المنيو. لو عايز يحجز ترابيزة قوله يضغط زر الحجز.\n\n"
        f"معلومات:\n{facts}\n"
        f"المواعيد: {INFO['hours']} | العنوان: {INFO['address']} | التوصيل: {INFO['delivery']['fee']} لـ {INFO['delivery']['areas']}"
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
    wants_order = bool(_ORDER.search(norm)) and not wants_booking
    hits = retrieve(message)
    action = "book" if wants_booking else ("menu" if wants_order else None)

    cfg = _llm_config()
    if cfg:
        try:
            facts = "\n".join(c.context for s, c in hits if s > 0.05)
            reply = _call_llm(cfg, message, history, facts)
            return {"reply": reply, "action": action, "suggestions": SUGGESTIONS, "mode": "llm"}
        except Exception as e:  # fall back to retrieval if the API fails
            print("LLM error, falling back:", e)

    if wants_booking:
        reply = "تمام! دوس على «احجز ترابيزة» واكتب العدد والمعاد، وهنأكدلك على طول 👇"
    elif wants_order and (not hits or hits[0][0] < 0.35):
        reply = "يا أهلاً! ضيف الأصناف اللي نفسك فيها من المنيو للسلة 🛒، وبعدين دوس «اطلب على واتساب» والأوردر يوصلنا جاهز."
    elif _GREET.search(norm) and len(norm.split()) <= 3:
        reply = f"أهلاً بيك في {INFO['name']} 👋 تحب تشوف المنيو، أرشحلك أكلة، ولا تحجز ترابيزة؟"
    elif _THANKS.search(norm):
        reply = "بالهنا والشفا مقدمًا 😋 لو احتجت أي حاجة أنا موجود"
    elif hits and hits[0][0] >= 0.18:
        reply = hits[0][1].answer
    else:
        reply = ("مش متأكد من الإجابة دي 🙏 ممكن تكلمنا واتساب على "
                 f"{INFO['phone']} وحد من المطعم هيرد عليك.")
    return {"reply": reply, "action": action, "suggestions": SUGGESTIONS, "mode": "local"}
