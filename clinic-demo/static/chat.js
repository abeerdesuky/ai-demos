const Chat = (() => {
  const box = document.getElementById("chatBox");
  const fab = document.getElementById("chatFab");
  const log = document.getElementById("chatLog");
  const sug = document.getElementById("chatSug");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const history = [];
  let started = false, busy = false;

  function add(role, text, action) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.textContent = text;
    if (action === "book") {
      const b = document.createElement("button");
      b.className = "act";
      b.textContent = "📅 احجز الآن";
      b.onclick = () => { close(); document.getElementById("book").scrollIntoView(); document.querySelector("#bookForm [name=name]").focus(); };
      el.appendChild(document.createElement("br"));
      el.appendChild(b);
    }
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function suggestions(list) {
    sug.replaceChildren(...(list || []).map(t => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = t;
      b.onclick = () => send(t);
      return b;
    }));
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
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: history.slice(-6) }),
      });
      const data = await r.json();
      typing.remove();
      const reply = r.ok ? data.reply : (data.detail || "حصلت مشكلة، جرب تاني");
      add("bot", reply, data.action);
      history.push({ role: "user", content: text }, { role: "assistant", content: reply });
      if (data.suggestions) suggestions(data.suggestions);
    } catch {
      typing.remove();
      add("bot", "مش قادر أتصل دلوقتي، جرب تاني بعد شوية 🙏");
    }
    busy = false;
    input.focus();
  }

  function open() {
    box.hidden = false;
    fab.classList.remove("pulse");
    if (!started) {
      started = true;
      add("bot", "أهلاً بيك 👋 أنا المساعد الذكي للعيادة. اسألني عن الأسعار، المواعيد، الأطباء، أو احجز ميعادك.");
      suggestions(["الأسعار", "مواعيد العيادة", "فيه تقسيط؟", "عايز أحجز"]);
    }
    input.focus();
  }
  function close() { box.hidden = true; }

  fab.onclick = () => (box.hidden ? open() : close());
  form.onsubmit = e => { e.preventDefault(); send(input.value); };
  setTimeout(() => fab.classList.add("pulse"), 2500);

  return { open, close, send };
})();

// Booking form
document.getElementById("bookForm").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = document.getElementById("bookMsg");
  const btn = f.querySelector("button");
  btn.disabled = true; msg.className = "form-msg"; msg.textContent = "جاري الإرسال...";
  try {
    const r = await fetch("/api/book", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(f))),
    });
    const data = await r.json();
    if (r.ok) { msg.classList.add("ok"); msg.textContent = data.message; f.reset(); }
    else {
      msg.classList.add("err");
      msg.textContent = typeof data.detail === "string" ? data.detail : "اتأكد من البيانات وجرب تاني";
    }
  } catch { msg.classList.add("err"); msg.textContent = "حصلت مشكلة في الاتصال"; }
  btn.disabled = false;
});
