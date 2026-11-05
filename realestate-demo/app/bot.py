"""
محرك البحث الذكي + الشات بوت لموقع العقارات.

- parse_query: بيفهم طلب العميل بالعامية ويحوّله لفلاتر
  (نوع الوحدة، بيع ولا إيجار، المنطقة، الميزانية، عدد الغرف، المميزات).
- search: بيدوّر في الوحدات، ولو مفيش حاجة مطابقة بيخفف الشروط واحدة واحدة ويعرض أقرب اختيارات.
- answer: بيرد على العميل. لو كلامه فيه طلب وحدة بيعرض نتايج، ولو سؤال عام بيرد من الأسئلة الشائعة.
  ولو فيه LLM_API_KEY، الرد بيتكتب بالذكاء الاصطناعي من النتايج الحقيقية بس.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections import Counter
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "realestate.json"
INFO = json.loads(DATA_FILE.read_text(encoding="utf-8"))
LISTINGS = INFO["listings"]
BY_ID = {l["id"]: l for l in LISTINGS}

# ---------------- text utils ----------------
_DIACRITICS = re.compile(r"[ؗ-ًؚ-ْـ]")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize(text: str) -> str:
    text = _DIACRITICS.sub("", (text or "").lower().translate(_AR_DIGITS))
    text = re.sub("[إأآا]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    text = text.replace("٫", ".").replace(",", "")
    text = re.sub(r"[^\w\s.]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has(norm: str, words: str) -> bool:
    return any(re.search(rf"(^|\s|[وبلف]){re.escape(normalize(w))}", norm) for w in words.split("|"))


# ---------------- query parsing ----------------
_WORD_NUM = {"واحد": 1, "وحده": 1, "اتنين": 2, "اثنين": 2, "تلات": 3, "تلاته": 3, "ثلاث": 3, "ثلاثه": 3,
             "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6}
TYPES = {"شقة": "شقه|شقق|استوديو|ستوديو", "فيلا": "فيلا|فيلل|فلل|فله", "تاون هاوس": "تاون|توين",
         "دوبلكس": "دوبلكس|دبلكس", "شاليه": "شاليه|شاليهات", "مكتب": "مكتب|اداري|اوفيس"}
FEATURES = {"جاردن": "جاردن|حديقه|جنينه", "حمام سباحة": "حمام سباحه|بيسين|بسين|سباحه", "روف": "روف",
            "بحري": "بحري", "فيو بحر": "فيو بحر|على البحر|ع البحر|صف اول", "مفروش": "مفروش|مفروشه|فرش"}

_MONEY = r"(\d+(?:\.\d+)?)\s*(مليون|مليونين|م\b|الف|k|ك\b)?"


def _parse_money(norm: str) -> list[float]:
    """Extract money amounts (EGP) in order of appearance."""
    s = norm
    s = re.sub(r"من\s*(\d+(?:\.\d+)?)\s*(?:ل|الي|لحد|حتي|-)\s*(\d+(?:\.\d+)?)\s*(مليون|الف)",
               lambda m: f"من {m.group(1)} {m.group(3)} ل {m.group(2)} {m.group(3)}", s)
    s = re.sub(r"\bمليونين(\s+و\s*نص)?", lambda m: " 2.5 مليون" if m.group(1) else " 2 مليون", s)
    s = re.sub(r"\bنص مليون", " 0.5 مليون", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*مليون\s+و\s*نص", lambda m: f"{float(m.group(1)) + .5} مليون", s)
    s = re.sub(r"(?<!\d)مليون\s+و\s*نص", "1.5 مليون", s)
    s = re.sub(r"(?<![\d.])\bمليون\b", "1 مليون", s) if not re.search(r"\d\s*مليون", s) else s
    out = []
    for m in re.finditer(_MONEY, s):
        n, unit = float(m.group(1)), (m.group(2) or "")
        if unit.startswith("مليون") or unit == "م":
            n *= 1_000_000
        elif unit in ("الف", "k", "ك"):
            n *= 1_000
        elif n < 10_000:          # small bare numbers are rooms/sizes, not prices
            continue
        out.append(n)
    return out


def parse_query(text: str) -> dict:
    norm = normalize(text)
    f: dict = {}

    if _has(norm, "ايجار|اجار|للايجار|يتاجر|مفروش|شهري"):
        f["purpose"] = "إيجار"
    elif _has(norm, "بيع|للبيع|تمليك|اشتري|شراء|اشترى|استثمار|تقسيط|مقدم"):
        f["purpose"] = "بيع"

    types = [t for t, kw in TYPES.items() if _has(norm, kw)]
    if types:
        f["types"] = types

    for a in INFO["areas"]:
        if any(_has(norm, x) for x in [a["name"], *a["aliases"].split()] if len(normalize(x)) > 2 or x.isdigit()):
            if a["name"] == "6 أكتوبر" and not _has(norm, "اكتوبر"):
                continue
            f["area"] = a["name"]
            break

    # rooms
    m = re.search(r"(\d+)\s*(غرف|غرفه|اوض|اوضه|نوم)", norm)
    if m:
        f["beds"] = int(m.group(1))
    else:
        for w, n in _WORD_NUM.items():
            if re.search(rf"\b{w}\s*(غرف|اوض|غرفه|اوضه)", norm):
                f["beds"] = n
                break
        if "غرفتين" in norm or "اوضتين" in norm:
            f["beds"] = 2
        elif _has(norm, "استوديو|ستوديو") and "beds" not in f:
            f["beds"] = 1

    # budget
    amounts = _parse_money(norm)
    if amounts:
        if len(amounts) >= 2 and re.search(r"\bمن\b.*\b(ل|لـ|الي|لحد|حتي)\b", norm):
            f["min_price"], f["max_price"] = min(amounts[:2]), max(amounts[:2])
        elif _has(norm, "فوق|اكتر من|اكثر من|مش اقل من|ابتداء من"):
            f["min_price"] = amounts[0]
        elif _has(norm, "حدود|حوالي|تقريبا"):
            f["min_price"], f["max_price"] = amounts[0] * 0.8, amounts[0] * 1.1
        else:  # تحت / أقل من / ميزانيتي / لحد ... default: a ceiling
            f["max_price"] = amounts[0]
        if "purpose" not in f:
            f["purpose"] = "إيجار" if max(amounts) < 300_000 else "بيع"

    feats = [k for k, kw in FEATURES.items() if _has(norm, kw)]
    if feats:
        f["features"] = feats
    if _has(norm, "تقسيط|قسط|اقساط|مقدم"):
        f["installment"] = True
    if _has(norm, "استلام فوري|جاهز|استلام حالا|فوري"):
        f["ready"] = True
    return f


# ---------------- search ----------------
def _match(l: dict, f: dict, slack: float = 1.1) -> bool:
    if f.get("purpose") and l["purpose"] != f["purpose"]:
        return False
    if f.get("types") and l["type"] not in f["types"]:
        return False
    if f.get("area") and l["area"] != f["area"]:
        return False
    if f.get("max_price") and l["price"] > f["max_price"] * slack:
        return False
    if f.get("min_price") and l["price"] < f["min_price"] * 0.9:
        return False
    if f.get("beds") and l["beds"] < f["beds"]:
        return False
    if any(x not in l["features"] and x != l["finishing"] for x in f.get("features", [])):
        return False
    if f.get("installment") and not l.get("installment"):
        return False
    if f.get("ready") and "فوري" not in l["delivery"] and "متاح" not in l["delivery"]:
        return False
    return True


def _rank(l: dict, f: dict) -> float:
    score = sum(1 for x in f.get("features", []) if x in l["features"] or x == l["finishing"])
    if f.get("beds"):
        score -= 0.3 * abs(l["beds"] - f["beds"])
    if f.get("max_price"):
        score -= 0.2 * max(0, l["price"] - f["max_price"]) / f["max_price"]
    return score


def _relax_steps(f: dict):
    """Yields (label, filters) progressively looser versions of f."""
    cur = dict(f)
    for key, label in [("features", "المميزات"), ("ready", "الاستلام الفوري"), ("installment", "التقسيط"),
                       ("beds", "عدد الغرف")]:
        if key in cur:
            cur = {k: v for k, v in cur.items() if k != key}
            yield label, cur
    if "max_price" in cur:
        cur = {**cur, "max_price": cur["max_price"] * 1.3}
        yield "الميزانية", cur
        cur = {k: v for k, v in cur.items() if k not in ("max_price", "min_price")}
        yield "الميزانية", cur
    if "area" in cur:
        cur = {k: v for k, v in cur.items() if k != "area"}
        yield "المنطقة", cur


def search(f: dict, limit: int = 4) -> tuple[list[dict], list[str]]:
    """Returns (results, relaxed_labels). If nothing matches, loosens filters step by step."""
    relaxed, stages = [], [(None, f), *_relax_steps(f)]
    for label, cur in stages:
        if label:
            relaxed.append(label)
        res = [l for l in LISTINGS if _match(l, cur)]
        if res:
            res.sort(key=lambda l: (-_rank(l, f), l["price"]))
            res = res[:limit]
            # report only the constraints the shown results actually miss
            checks = {"المميزات": "features", "الاستلام الفوري": "ready", "التقسيط": "installment",
                      "عدد الغرف": "beds", "الميزانية": "max_price", "المنطقة": "area"}
            diff = [lb for lb in dict.fromkeys(relaxed)
                    if any(not _match(l, {checks[lb]: f[checks[lb]]}) for l in res if checks[lb] in f)]
            return res, diff
    return [], relaxed


# ---------------- formatting ----------------
def fmt_price(l: dict) -> str:
    p = l["price"]
    if l["purpose"] == "إيجار":
        return f"{p:,.0f} ج / {l.get('period', 'شهر')}"
    return f"{p / 1e6:.2f}".rstrip("0").rstrip(".") + " مليون ج" if p >= 1e6 else f"{p:,.0f} ج"


def card(l: dict) -> dict:
    return {"id": l["id"], "title": l["title"], "area": l["area"], "price": fmt_price(l), "beds": l["beds"],
            "size": l["size"], "type": l["type"], "art": l["art"]}


def describe_filters(f: dict) -> str:
    parts = []
    if f.get("types"):
        parts.append(" أو ".join(f["types"]))
    if f.get("purpose"):
        parts.append("للإيجار" if f["purpose"] == "إيجار" else "للبيع")
    if f.get("beds"):
        parts.append(f"{f['beds']} غرف")
    if f.get("area"):
        parts.append(f"في {f['area']}")
    if f.get("max_price") and f.get("min_price"):
        parts.append(f"من {f['min_price'] / 1e6:g} لـ {f['max_price'] / 1e6:g} مليون" if f["max_price"] >= 1e6
                     else f"من {f['min_price']:,.0f} لـ {f['max_price']:,.0f} ج")
    elif f.get("max_price"):
        parts.append(f"تحت {f['max_price'] / 1e6:g} مليون" if f["max_price"] >= 1e6 else f"تحت {f['max_price']:,.0f} ج")
    elif f.get("min_price"):
        parts.append(f"فوق {f['min_price'] / 1e6:g} مليون" if f["min_price"] >= 1e6 else f"فوق {f['min_price']:,.0f} ج")
    if f.get("features"):
        parts.append("، ".join(f["features"]))
    if f.get("installment"):
        parts.append("بالتقسيط")
    if f.get("ready"):
        parts.append("استلام فوري")
    return " ".join(parts)


# ---------------- FAQ retrieval ----------------
def _vector(text: str) -> Counter:
    vec: Counter = Counter()
    for w in normalize(text).split():
        w = re.sub(r"^(وال|بال|فال|كال|لل|ال)", "", w) or w
        p = f" {w} "
        for n in (2, 3, 4):
            for i in range(len(p) - n + 1):
                vec[p[i:i + n]] += 1
    return vec


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


_FAQ = [(_vector(f"{f['q']} {f.get('tags', '')}"), f["a"]) for f in INFO["faq"]] + [
    (_vector("العنوان المكتب فين مكانكم الفرع"), f"مكتبنا في {INFO['address']}."),
    (_vector("مواعيد العمل بتفتحوا امتى شغالين"), f"مواعيدنا: {INFO['hours']}."),
    (_vector("رقم التليفون واتساب تواصل اكلمكم"), f"تقدر تكلمنا على {INFO['phone']} أو واتساب بنفس الرقم."),
    (_vector("مناطق بتشتغلوا فين المناطق المتاحه"),
     "بنشتغل في: " + "، ".join(a["name"] for a in INFO["areas"]) + "."),
]

SUGGESTIONS = ["شقة 3 غرف في التجمع تحت 7 مليون", "فيلا في زايد", "إيجار مفروش", "تقسيط على 10 سنين", "عايز أبيع شقتي"]
_REFINE = re.compile(r"^(طب|طيب|ولو|و|بدل|طيب و|وفي|طب في|ارخص|اغلي|اكبر|اصغر)\b")


def _llm(message: str, facts: str) -> str | None:
    key = os.getenv("LLM_API_KEY")
    if not key:
        return None
    url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    sys = (f"أنت مستشار عقاري في {INFO['name']}. رد بالمصري بشكل مختصر ومحترف (2-3 جمل). "
           "اعتمد فقط على المعلومات التالية، ومتذكرش وحدات أو أسعار مش موجودة فيها. "
           "الوحدات بتظهر للعميل ككروت تحت ردك، فماتكررش تفاصيلها كلها؛ لخّص وشجعه يحجز معاينة.\n\n" + facts)
    body = {"model": os.getenv("LLM_MODEL", "gpt-4o-mini"), "temperature": 0.3, "max_tokens": 250,
            "messages": [{"role": "system", "content": sys}, {"role": "user", "content": message}]}
    try:
        req = urllib.request.Request(url, json.dumps(body).encode(),
                                     {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("LLM error, falling back:", e)
        return None


def answer(message: str, history: list[dict] | None = None) -> dict:
    message = (message or "").strip()[:500]
    norm = normalize(message)
    base = {"suggestions": SUGGESTIONS, "listings": []}
    if not norm:
        return {**base, "reply": "اكتبلي إنت بتدور على إيه 🙂"}

    if _has(norm, "معاينه|كلموني|تكلموني|اتواصل معايا|احجز") and not _has(norm, "ابيع|اأجر"):
        return {**base, "reply": "تمام! اكتب بياناتك في الفورم وفريق المبيعات هيكلمك يحدد معاد المعاينة 👇",
                "action": "lead"}

    f = parse_query(message)
    # merge with previous request when the user is refining ("طب في زايد؟")
    short_followup = f and not ({"types", "area"} & f.keys()) and len(norm.split()) <= 4
    if history and (_REFINE.search(norm) or short_followup or (f and len(f) == 1)):
        prev_user = [h["content"] for h in history if h.get("role") == "user" and isinstance(h.get("content"), str)]
        if prev_user:
            prev = parse_query(prev_user[-1])
            if prev:
                if "types" in f or "purpose" in f:
                    prev.pop("purpose", None) if "purpose" in f else None
                f = {**prev, **f}

    search_keys = {"types", "area", "beds", "max_price", "min_price", "features", "installment", "ready"}
    is_search = bool(search_keys & f.keys()) or ("purpose" in f and not _has(norm, "ابيع|اأجر|شقتي|وحدتي"))
    if is_search:
        results, relaxed = search(f)
        desc = describe_filters(f)
        if not results:
            reply = f"للأسف مفيش حاجة متاحة دلوقتي بالمواصفات دي ({desc}) 🙏 سيب رقمك ونبلغك أول ما ينزل حاجة مناسبة."
            return {**base, "reply": reply, "action": "lead", "filters": f}
        n = len(results)
        count = {1: "وحدة واحدة", 2: "وحدتين"}.get(n, f"{n} وحدات")
        if relaxed:
            reply = (f"مفيش وحدة مطابقة 100% لطلبك ({desc}) 🙏 بس دي أقرب {count} ليه، "
                     f"مع اختلاف في {' و'.join(relaxed)} 👇")
        else:
            reply = f"لقيتلك {count} {'مناسبتين' if n == 2 else 'مناسبة'} لطلبك ({desc}) 👇"
        facts = "\n".join(f"- {l['title']} | {l['area']} | {fmt_price(l)} | {l['beds']} غرف | {l['size']} م | "
                          f"{l['finishing']} | {l['delivery']}" for l in results)
        reply = _llm(message, f"طلب العميل: {desc}\nالنتايج:\n{facts}") or reply
        return {**base, "reply": reply, "listings": [card(l) for l in results], "filters": f,
                "suggestions": ["احجز معاينة", "عندكم تقسيط؟", "استلام فوري؟"]}

    if re.match(r"^(" + "|".join(normalize(w) for w in "السلام سلام اهلا هاي هلو صباح مساء hi hello".split()) + ")", norm):
        return {**base, "reply": f"أهلاً بيك في {INFO['name']} 👋 قولّي بتدور على إيه بالظبط، "
                                 "مثلاً: «شقة 3 غرف في التجمع تحت 6 مليون» وأنا أطلّعلك المناسب."}
    if _has(norm, "شكرا|متشكر|تسلم"):
        return {**base, "reply": "العفو! ربنا يرزقك بالبيت اللي تحبه 🏡"}

    q = _vector(message)
    score, ans = max(((_cos(q, v), a) for v, a in _FAQ), key=lambda x: x[0])
    if score >= 0.3:
        llm = _llm(message, f"معلومة: {ans}")
        return {**base, "reply": llm or ans}
    return {**base, "reply": "مش متأكد إني فهمتك 🙏 جرّب تكتب نوع الوحدة والمنطقة والميزانية، "
                             "أو سيب رقمك ومستشار عقاري هيكلمك.", "action": "lead"}
