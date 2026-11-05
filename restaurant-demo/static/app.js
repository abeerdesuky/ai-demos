const $ = s => document.querySelector(s);

async function postJSON(url, data) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "اتأكد من البيانات وجرب تاني");
  return body;
}

/* ---------- Menu tabs ---------- */
document.querySelectorAll(".tab").forEach(t => t.onclick = () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x === t));
  document.querySelectorAll(".items").forEach(x => x.classList.toggle("hide", x.id !== t.dataset.cat));
});

/* ---------- Cart ---------- */
const Cart = (() => {
  const box = $("#cart"), fab = $("#cartFab");
  let items = {};
  try { items = JSON.parse(localStorage.getItem("cart") || "{}"); } catch {}
  for (const id in items) if (!MENU[id]) delete items[id];

  const save = () => { try { localStorage.setItem("cart", JSON.stringify(items)); } catch {} };
  const subtotal = () => Object.entries(items).reduce((s, [id, q]) => s + MENU[id].price * q, 0);

  function render() {
    const count = Object.values(items).reduce((a, b) => a + b, 0);
    $("#cartCount").textContent = count;
    const list = $("#cartList");
    list.replaceChildren();
    if (!count) list.innerHTML = '<p class="empty">السلة فاضية.. ضيف حاجة حلوة من المنيو 😋</p>';
    for (const [id, q] of Object.entries(items)) {
      const row = document.createElement("div");
      row.className = "cart-row";
      const n = document.createElement("div");
      n.className = "n";
      n.textContent = MENU[id].name;
      const sm = document.createElement("small");
      sm.textContent = `${MENU[id].price * q} ج`;
      n.appendChild(sm);
      const qty = document.createElement("div");
      qty.className = "qty";
      const minus = Object.assign(document.createElement("button"), { textContent: "−", type: "button", onclick: () => set(id, q - 1) });
      const plus = Object.assign(document.createElement("button"), { textContent: "+", type: "button", onclick: () => set(id, q + 1) });
      qty.append(minus, Object.assign(document.createElement("b"), { textContent: q }), plus);
      row.append(n, qty);
      list.appendChild(row);
    }
    const sub = subtotal();
    const fee = sub === 0 || sub >= RULES.freeOver ? 0 : RULES.fee;
    $("#sub").textContent = `${sub} ج`;
    $("#fee").textContent = sub >= RULES.freeOver ? "مجاني 🎉" : `${fee} ج`;
    $("#tot").textContent = `${sub + fee} ج`;
    $("#hint").textContent = sub && sub < RULES.min ? `الحد الأدنى ${RULES.min} ج — ضيف ${RULES.min - sub} ج كمان`
      : sub && sub < RULES.freeOver ? `فاضلك ${RULES.freeOver - sub} ج والتوصيل يبقى مجاني` : "";
  }
  function set(id, q) {
    if (q <= 0) delete items[id]; else items[id] = Math.min(q, 20);
    save(); render();
  }
  function add(id) {
    set(id, (items[id] || 0) + 1);
    fab.classList.remove("bump"); void fab.offsetWidth; fab.classList.add("bump");
  }
  const open = () => { box.hidden = false; };
  const close = () => { box.hidden = true; };

  fab.onclick = open;
  document.querySelectorAll(".add").forEach(b => b.onclick = () => {
    add(b.dataset.id);
    b.textContent = "✓ اتضاف"; b.classList.add("done");
    setTimeout(() => { b.textContent = "+ أضف"; b.classList.remove("done"); }, 900);
  });

  $("#orderForm").onsubmit = async e => {
    e.preventDefault();
    const f = e.target, msg = f.querySelector(".form-msg");
    msg.className = "form-msg";
    if (!Object.keys(items).length) { msg.classList.add("err"); msg.textContent = "السلة فاضية"; return; }
    // Open the tab synchronously so popup blockers allow it, then point it to WhatsApp
    const win = window.open("", "_blank");
    try {
      const data = await postJSON("/api/order", { ...Object.fromEntries(new FormData(f)), items });
      msg.classList.add("ok"); msg.textContent = `تم ✅ الإجمالي ${data.total} ج — كمّل الإرسال على واتساب`;
      if (win) win.location = data.whatsapp_url; else location.href = data.whatsapp_url;
      items = {}; save(); render(); f.reset();
    } catch (err) {
      if (win) win.close();
      msg.classList.add("err"); msg.textContent = err.message;
    }
  };

  render();
  return { open, close, add };
})();

/* ---------- Reservation ---------- */
$("#resForm").onsubmit = async e => {
  e.preventDefault();
  const f = e.target, msg = f.querySelector(".form-msg"), btn = f.querySelector("button");
  btn.disabled = true; msg.className = "form-msg"; msg.textContent = "جاري الإرسال...";
  try {
    const d = Object.fromEntries(new FormData(f));
    d.guests = Number(d.guests);
    const r = await postJSON("/api/reserve", d);
    msg.classList.add("ok"); msg.textContent = r.message; f.reset();
  } catch (err) { msg.classList.add("err"); msg.textContent = err.message; }
  btn.disabled = false;
};

/* ---------- Chat ---------- */
const Chat = (() => {
  const box = $("#chatBox"), fab = $("#chatFab"), log = $("#chatLog"), sug = $("#chatSug"), input = $("#chatInput");
  const history = [];
  let started = false, busy = false;

  function add(role, text, action) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.textContent = text;
    const actions = { book: ["📅 احجز ترابيزة", "#reserve"], menu: ["🍽️ افتح المنيو", "#menu"] };
    if (actions[action]) {
      const [label, target] = actions[action];
      const b = Object.assign(document.createElement("button"), { className: "act", textContent: label });
      b.onclick = () => { close(); $(target).scrollIntoView(); };
      el.append(document.createElement("br"), b);
    }
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function suggestions(list) {
    sug.replaceChildren(...(list || []).map(t =>
      Object.assign(document.createElement("button"), { type: "button", textContent: t, onclick: () => send(t) })));
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
      const data = await postJSON("/api/chat", { message: text, history: history.slice(-6) });
      typing.remove();
      add("bot", data.reply, data.action);
      history.push({ role: "user", content: text }, { role: "assistant", content: data.reply });
      suggestions(data.suggestions);
    } catch (err) {
      typing.remove();
      add("bot", err.message || "مش قادر أتصل دلوقتي، جرب تاني 🙏");
    }
    busy = false;
    input.focus();
  }
  function open() {
    box.hidden = false;
    fab.classList.remove("pulse");
    if (!started) {
      started = true;
      add("bot", "أهلاً بيك في بيت الزعتر 👋 محتار تاكل إيه؟ قولّي وأنا أرشحلك، أو اسألني عن الأسعار والتوصيل.");
      suggestions(["ترشحلي إيه؟", "المنيو", "فيه توصيل؟", "عندكم نباتي؟", "احجز ترابيزة"]);
    }
    input.focus();
  }
  function close() { box.hidden = true; }

  fab.onclick = () => (box.hidden ? open() : close());
  $("#chatForm").onsubmit = e => { e.preventDefault(); send(input.value); };
  setTimeout(() => fab.classList.add("pulse"), 2500);
  return { open, close, send };
})();
