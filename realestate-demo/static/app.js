const $ = s => document.querySelector(s);
const BY_ID = Object.fromEntries(UNITS.map(u => [u.id, u]));
const img = u => `/static/art/${u.art}.svg`;
const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids.filter(k => k != null));
  return e;
};
const money = n => n >= 1e6 ? `${(n / 1e6).toFixed(2).replace(/\.?0+$/, "")} مليون ج` : `${Math.round(n).toLocaleString("en")} ج`;

async function api(url, data) {
  const r = await fetch(url, data ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) } : {});
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "اتأكد من البيانات وجرب تاني");
  return body;
}

/* ---------------- Listings ---------------- */
const Units = (() => {
  const state = { purpose: "", type: "", area: "", beds: 0, max: 0, ids: null };

  function cardEl(u) {
    const rent = u.purpose === "إيجار";
    const imgBox = el("div", { className: "img" },
      el("span", { className: "tag" + (rent ? " rent" : ""), textContent: rent ? "للإيجار" : "للبيع" }),
      el("span", { className: "price-b", textContent: u.price }));
    imgBox.style.backgroundImage = `url(${img(u)})`;
    const specs = el("div", { className: "specs" },
      u.beds ? el("span", { textContent: `🛏️ ${u.beds} غرف` }) : el("span", { textContent: "🏢 إداري" }),
      el("span", { textContent: `🛁 ${u.baths}` }), el("span", { textContent: `📐 ${u.size} م²` }));
    const chips = el("div", { className: "chips" }, ...u.features.slice(0, 3).map(f => el("span", { className: "chip", textContent: f })));
    const card = el("article", { className: "unit", tabIndex: 0 }, imgBox,
      el("div", { className: "body" }, el("h3", { textContent: u.title }),
        el("div", { className: "loc", textContent: `📍 ${u.area} — ${u.compound}` }), chips, specs));
    card.onclick = () => Detail.open(u.id);
    card.onkeydown = e => { if (e.key === "Enter") Detail.open(u.id); };
    return card;
  }

  function render() {
    let list = state.ids ? state.ids.map(id => BY_ID[id]) : UNITS.filter(u =>
      (!state.purpose || u.purpose === state.purpose) && (!state.type || u.type === state.type) &&
      (!state.area || u.area === state.area) && (!state.beds || u.beds >= state.beds) &&
      (!state.max || (u.purpose === "بيع" && u.raw_price <= state.max)));
    if (state.ids && state.purpose) list = list.filter(u => u.purpose === state.purpose);
    const grid = $("#grid");
    grid.replaceChildren(...list.map(cardEl));
    if (!list.length) grid.append(el("p", { className: "empty", textContent: "مفيش وحدات بالمواصفات دي حاليًا. جرّب تغيّر الفلاتر أو اسأل المستشار الذكي 💬" }));
    $("#count").textContent = `${list.length} وحدة`;
  }

  function clearAI() { state.ids = null; $("#aiNote").hidden = true; }

  async function smart(q) {
    q = q.trim();
    if (!q) return;
    $("#smartQ").value = q;
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}`);
      state.ids = r.ids;
      const note = $("#aiNote");
      note.replaceChildren(
        el("span", { textContent: r.desc ? `🤖 فهمت إنك بتدور على: ${r.desc}` + (r.relaxed.length ? ` — مفيش تطابق كامل، وسّعنا: ${r.relaxed.join(" و")}` : "") : "🤖 مافهمتش مواصفات محددة، دي كل الوحدات" }),
        el("button", { textContent: "إلغاء البحث", onclick: () => { clearAI(); render(); } }));
      note.hidden = false;
      render();
      note.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { alert(e.message); }
  }

  document.querySelectorAll(".seg button").forEach(b => b.onclick = () => {
    document.querySelectorAll(".seg button").forEach(x => x.classList.toggle("on", x === b));
    state.purpose = b.dataset.p; render();
  });
  for (const [id, key, num] of [["#fType", "type"], ["#fArea", "area"], ["#fBeds", "beds", 1], ["#fMax", "max", 1]]) {
    $(id).onchange = e => { state[key] = num ? Number(e.target.value) : e.target.value; clearAI(); render(); };
  }
  $("#smart").onsubmit = e => { e.preventDefault(); smart($("#smartQ").value); };
  document.querySelectorAll(".ex").forEach(b => b.onclick = () => smart(b.textContent));
  render();
  return { render, smart };
})();

/* ---------------- Detail modal ---------------- */
const Detail = (() => {
  const modal = $("#pModal");
  function open(id) {
    const u = BY_ID[id];
    if (!u) return;
    const pic = el("div", { className: "p-img" });
    pic.style.backgroundImage = `url(${img(u)})`;
    const spec = (k, v) => el("div", {}, el("b", { textContent: v }), k);
    const body = el("div", { className: "p-body" },
      el("div", { className: "p-top" },
        el("div", {}, el("h3", { textContent: u.title }), el("div", { className: "loc", textContent: `📍 ${u.area} — ${u.compound}` })),
        el("div", { className: "p-price", textContent: u.price })),
      el("div", { className: "p-specs" },
        spec("الغرف", u.beds || "—"), spec("الحمامات", u.baths), spec("المساحة", `${u.size} م²`), spec("التشطيب", u.finishing)),
      el("p", { textContent: u.desc }),
      el("div", { className: "chips" }, ...u.features.map(f => el("span", { className: "chip", textContent: f })),
        el("span", { className: "chip", textContent: `🗓️ ${u.delivery}` })));
    if (u.installment) {
      const down = u.raw_price * u.installment.down / 100;
      const monthly = (u.raw_price - down) / (u.installment.years * 12);
      body.append(el("div", { className: "p-plan" },
        el("b", { textContent: "💳 خطة السداد: " }),
        `مقدم ${u.installment.down}% (${money(down)}) والباقي على ${u.installment.years} سنين ≈ ${money(monthly)} في الشهر`));
    }
    body.append(el("div", { className: "p-actions" },
      el("button", { className: "btn btn-dark", textContent: "📅 احجز معاينة", onclick: () => { modal.close(); Lead.open(u.id); } }),
      el("a", { className: "btn btn-wa", target: "_blank", rel: "noopener", textContent: "واتساب",
        href: `${document.querySelector(".btn-wa").href}?text=${encodeURIComponent(`مهتم بالوحدة ${u.id} - ${u.title}`)}` })));
    $("#pBody").replaceChildren(pic, body);
    modal.showModal();
  }
  modal.addEventListener("click", e => { if (e.target === modal) modal.close(); });
  return { open };
})();

/* ---------------- Lead modal ---------------- */
const Lead = (() => {
  const modal = $("#lModal"), form = $("#leadForm");
  function open(id, source = "form") {
    const u = BY_ID[id];
    form.listing_id.value = u ? u.id : "";
    form.source.value = source;
    $("#lFor").textContent = u ? `الوحدة: ${u.title} (${u.price})` : "سيب بياناتك ومستشار عقاري هيكلمك.";
    form.querySelector(".form-msg").textContent = "";
    if (u && u.purpose === "إيجار") form.payment.value = "إيجار";
    modal.showModal();
  }
  form.onsubmit = async e => {
    e.preventDefault();
    const msg = form.querySelector(".form-msg"), btn = form.querySelector("button");
    btn.disabled = true; msg.className = "form-msg"; msg.textContent = "جاري الإرسال...";
    try {
      const d = Object.fromEntries(new FormData(form));
      d.budget = Number(d.budget);
      const r = await api("/api/lead", d);
      msg.classList.add("ok"); msg.textContent = r.message;
      form.reset();
      setTimeout(() => modal.close(), 2200);
    } catch (err) { msg.classList.add("err"); msg.textContent = err.message; }
    btn.disabled = false;
  };
  modal.addEventListener("click", e => { if (e.target === modal) modal.close(); });
  return { open };
})();

/* ---------------- Calculator ---------------- */
(() => {
  const p = $("#cPrice"), d = $("#cDown"), y = $("#cYears");
  function calc() {
    const price = +p.value, down = price * d.value / 100, monthly = (price - down) / (y.value * 12);
    $("#cPriceV").textContent = money(price);
    $("#cDownV").textContent = `${d.value}%`;
    $("#cYearsV").textContent = `${y.value} سنين`;
    $("#cDownAmt").textContent = money(down);
    $("#cMonthly").textContent = money(monthly);
  }
  [p, d, y].forEach(i => i.oninput = calc);
  calc();
})();

/* ---------------- Chat ---------------- */
const Chat = (() => {
  const box = $("#chatBox"), fab = $("#chatFab"), log = $("#chatLog"), sug = $("#chatSug"), input = $("#chatInput");
  const history = [];
  let started = false, busy = false;

  function add(role, text, action, listings) {
    const m = el("div", { className: `msg ${role}`, textContent: text });
    if (action === "lead") {
      m.append(el("br"), el("button", { className: "act", textContent: "📞 سيب رقمك", onclick: () => Lead.open("", "chat") }));
    }
    log.append(m);
    if (listings && listings.length) {
      log.append(el("div", { className: "mini-list" }, ...listings.map(l => {
        const b = el("button", { className: "mini", type: "button" },
          el("img", { src: img(l), alt: "" }),
          el("div", {}, el("b", { textContent: l.title }), el("span", { textContent: `📍 ${l.area} · ${l.beds ? l.beds + " غرف · " : ""}${l.size} م²` }),
            el("br"), el("em", { textContent: l.price })));
        b.onclick = () => Detail.open(l.id);
        return b;
      })));
    }
    log.scrollTop = log.scrollHeight;
    return m;
  }
  function suggestions(list) {
    sug.replaceChildren(...(list || []).map(t => el("button", { type: "button", textContent: t, onclick: () => send(t) })));
  }
  async function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true;
    add("user", text);
    input.value = "";
    const typing = add("bot", "");
    typing.classList.add("typing");
    typing.innerHTML = "<span></span><span></span><span></span>";
    try {
      const r = await api("/api/chat", { message: text, history: history.slice(-6) });
      typing.remove();
      add("bot", r.reply, r.action, r.listings);
      history.push({ role: "user", content: text }, { role: "assistant", content: r.reply });
      suggestions(r.suggestions);
    } catch (err) {
      typing.remove();
      add("bot", err.message || "مش قادر أتصل دلوقتي 🙏");
    }
    busy = false;
    input.focus();
  }
  function open() {
    box.hidden = false;
    fab.classList.remove("pulse");
    if (!started) {
      started = true;
      add("bot", "أهلاً بيك 👋 أنا المستشار العقاري الذكي. قولّي بتدور على إيه بكلامك العادي، وأنا أطلّعلك أنسب الوحدات.");
      suggestions(["شقة 3 غرف في التجمع تحت 7 مليون", "فيلا في زايد", "إيجار مفروش", "تقسيط على 10 سنين", "هل فيه عمولة؟"]);
    }
    input.focus();
  }
  function close() { box.hidden = true; }
  fab.onclick = () => (box.hidden ? open() : close());
  $("#chatForm").onsubmit = e => { e.preventDefault(); send(input.value); };
  setTimeout(() => fab.classList.add("pulse"), 2500);
  return { open, close, send };
})();
