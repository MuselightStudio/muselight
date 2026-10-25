// Muselight web app: Muselight Credits only (the Windows app adds own provider accounts, GPUs and the bigger tools).
"use strict";

// the Credits server: api.muselight.studio in production; a local server while testing; ?api= overrides only on this PC (below)
// ?api= only works when testing on this PC: on the live site a link could otherwise send someone's sign-in to another server
const LOCAL = /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
const API = ((LOCAL && new URLSearchParams(location.search).get("api")) || (LOCAL ? "http://127.0.0.1:8080" : "https://api.muselight.studio")).replace(/\/$/, "");
const SUPABASE_JS = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = v => "$" + (Math.abs(v) < 1 && v !== 0 ? Number(v).toFixed(3).replace(/0$/, "") : Number(v).toFixed(2));
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} } };

let CFG = {}, ON = null, SB = null, ME = null, MODELS = [], LATEST = [], HIST = [], HIST_DONE = false, mode = "signup";

function toast(msg, ms = 4000) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.body.append(t);
  setTimeout(() => t.remove(), ms);
}

// ---------- talking to the Credits server ----------
async function token() {
  if (SB) { const { data } = await SB.auth.getSession(); if (data.session) return data.session.access_token; }
  return store.get("ml_token");
}
async function api(path, body, method) {
  const t = await token();
  const r = await fetch(API + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...(t ? { Authorization: "Bearer " + t } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(d.error || `Something went wrong (${r.status})`); e.status = r.status; throw e; }
  return d;
}

// ---------- start ----------
async function boot() {
  try { CFG = await api("/v1/config"); } catch { CFG = {}; }
  if (CFG.supabase_url && CFG.supabase_anon_key) {
    await new Promise((ok, no) => { const s = document.createElement("script"); s.src = SUPABASE_JS; s.onload = ok; s.onerror = no; document.head.append(s); }).catch(() => {});
    if (window.supabase) {
      SB = window.supabase.createClient(CFG.supabase_url, CFG.supabase_anon_key, { auth: { persistSession: true, detectSessionInUrl: true } });
      SB.auth.onAuthStateChange((ev) => { if (ev === "PASSWORD_RECOVERY") showReset(); else if (ev === "SIGNED_IN") enter(); else if (ev === "SIGNED_OUT") showAuth(); });
      try {  // only show the sign-in options switched on in Supabase
        ON = (await (await fetch(CFG.supabase_url + "/auth/v1/settings", { headers: { apikey: CFG.supabase_anon_key } })).json()).external || null;
      } catch {}
    }
  }
  await telegramReturn();
  if (location.hash.includes("type=recovery")) return showReset();
  if (await token()) { try { return await enter(); } catch { store.set("ml_token", null); } }
  showAuth(location.hash === "#signin" ? "signin" : "signup");
}

// ---------- sign-in ----------
function setAuthMsg(err, ok) {
  $("#authErr").hidden = !err; $("#authErr").textContent = err || "";
  $("#authOk").hidden = !ok; $("#authOk").textContent = ok || "";
}
function showAuth(m = mode) {
  mode = m;
  $("#appShell").hidden = true; $("#auth").hidden = false;
  const up = mode === "signup";
  $("#authTitle").textContent = up ? "Create your account" : "Welcome back";
  $("#authSub").textContent = up ? "Every great AI model, one balance." : "Sign in to keep creating.";
  $("#authSeg").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
  $("#oauth").hidden = !SB && !CFG.telegram_bot;
  $("#oauth").querySelectorAll("[data-provider]").forEach(b => b.hidden = !SB || (ON && !ON[b.dataset.provider]));
  $("#orline").hidden = $("#emailForm").hidden = !SB;
  $("#codeForm").hidden = !!SB; $("#resetForm").hidden = true; $("#backToEmail").hidden = $("#authSeg").hidden = !SB;
  $("#agreeRow").hidden = !up; $("#forgot").hidden = up;
  $("#emailGo").textContent = up ? "Create account" : "Sign in";
  $("#password").autocomplete = up ? "new-password" : "current-password";
  telegramButton();
  googleButton();
  setAuthMsg();
}
// Google: its own button, so its sign-in popup names muselight.studio rather than our sign-in provider's address
const GOOGLE_CLIENT_ID = "612597343652-nj6n9dpg7m5b3heggmr6uni6j9ggq9rq.apps.googleusercontent.com";
let gsi = null;
async function googleButton() {
  const box = $("#gbtn"), ours = $('#oauth [data-provider="google"]');
  box.hidden = true; ours.hidden = !SB || (ON && !ON.google);
  // on sign-up, our own button stays until the terms are ticked (clicking it says so); Google's appears once they are
  if (!SB || (ON && !ON.google) || (mode === "signup" && !$("#agree").checked)) return;
  gsi ||= new Promise((ok, no) => { const s = document.createElement("script"); s.src = "https://accounts.google.com/gsi/client"; s.onload = ok; s.onerror = no; document.head.append(s); });
  try { await gsi; } catch { gsi = null; return; }  // Google's script didn't load: our button still signs in (by redirect)
  const raw = crypto.randomUUID();  // Google signs the hash of it into the token; Supabase checks the token against it
  const hashed = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)))].map(b => b.toString(16).padStart(2, "0")).join("");
  google.accounts.id.initialize({ client_id: GOOGLE_CLIENT_ID, nonce: hashed, ux_mode: "popup", callback: async r => {
    const { error } = await SB.auth.signInWithIdToken({ provider: "google", token: r.credential, nonce: raw });
    if (error) { setAuthMsg(error.message); googleButton(); }  // a fresh one-time code for another try
  } });
  box.innerHTML = ""; box.hidden = false;  // sits invisibly over our button (see app.css), so ours is what people see
  google.accounts.id.renderButton(box, { theme: "filled_black", size: "large", shape: "rectangular",
    text: mode === "signup" ? "signup_with" : "continue_with", width: Math.min(400, ours.offsetWidth || 360) });
  cover(box, ours);
}
$("#agree").addEventListener("change", () => { googleButton(); telegramButton(); });
function telegramButton() {
  const box = $("#tgbox"), ours = $("#tgBtn");
  box.innerHTML = ""; box.hidden = true;
  $("#tgwrap").hidden = !CFG.telegram_bot;
  // on sign-up, clicking ours asks for the terms first; Telegram's own button only goes over it once they're ticked
  if (!CFG.telegram_bot || (mode === "signup" && !$("#agree").checked)) return;
  const s = document.createElement("script");
  s.async = true; s.src = "https://telegram.org/js/telegram-widget.js?22";
  s.dataset.telegramLogin = CFG.telegram_bot; s.dataset.size = "large"; s.dataset.requestAccess = "";
  s.dataset.authUrl = location.origin + location.pathname;  // Telegram sends people back here with a signed login
  box.append(s); box.hidden = false;
  cover(box, ours);
}
$("#tgBtn").onclick = () => setAuthMsg("Please tick the box to accept the terms first.");
// a provider's real button sits invisibly over ours (see app.css): stretch it to fill ours, so a click anywhere on ours reaches it
function cover(box, ours) {
  box.onmouseenter = () => ours.classList.add("hover");
  box.onmouseleave = () => ours.classList.remove("hover");
  let tries = 0;
  (function fit() {
    const f = box.querySelector("iframe");
    if (!f || !f.offsetWidth) { if (++tries < 50) setTimeout(fit, 100); return; }
    const stretch = () => f.style.transform = `scale(${ours.offsetWidth / f.offsetWidth}, ${ours.offsetHeight / f.offsetHeight})`;
    stretch();
    new ResizeObserver(stretch).observe(f);  // Telegram resizes its button after it loads
  })();
}
async function telegramReturn() {
  const q = new URLSearchParams(location.search);
  if (!q.get("hash") || !q.get("id") || !q.get("auth_date")) return;
  const d = {}; for (const k of ["id", "first_name", "last_name", "username", "photo_url", "auth_date", "hash"]) if (q.get(k) != null) d[k] = q.get(k);
  history.replaceState(null, "", location.pathname);
  try { store.set("ml_token", (await api("/v1/auth/telegram", d)).token); } catch (e) { toast(e.message); }
}
$("#authSeg").onclick = e => { const b = e.target.closest("button"); if (b) showAuth(b.dataset.mode); };
$("#oauth").addEventListener("click", async e => {
  const b = e.target.closest("[data-provider]"); if (!b || !SB) return;
  if (mode === "signup" && !$("#agree").checked) return setAuthMsg("Please tick the box to accept the terms first.");
  const { error } = await SB.auth.signInWithOAuth({ provider: b.dataset.provider, options: { redirectTo: location.origin + location.pathname } });
  if (error) setAuthMsg(error.message);
});
$("#emailForm").onsubmit = async e => {
  e.preventDefault(); setAuthMsg();
  const email = $("#email").value.trim(), password = $("#password").value;
  if (mode === "signup") {
    if (!$("#agree").checked) return setAuthMsg("Please tick the box to accept the terms first.");
    const { data, error } = await SB.auth.signUp({ email, password, options: { emailRedirectTo: location.origin + location.pathname } });
    if (error) return setAuthMsg(error.message);
    if (!data.session) return setAuthMsg(null, "Check your inbox: we've sent you a link to confirm your email.");
  } else {
    const { error } = await SB.auth.signInWithPassword({ email, password });
    if (error) return setAuthMsg(error.message === "Invalid login credentials" ? "That email and password don't match." : error.message);
  }
};
$("#forgot").onclick = async e => {
  e.preventDefault();
  const email = $("#email").value.trim(); if (!email) return setAuthMsg("Type your email above first.");
  const { error } = await SB.auth.resetPasswordForEmail(email, { redirectTo: location.origin + location.pathname });
  setAuthMsg(error && error.message, !error && "If that email has an account, a reset link is on its way.");
};
function showReset() { $("#appShell").hidden = true; $("#auth").hidden = false; $("#emailForm").hidden = $("#oauth").hidden = $("#orline").hidden = $("#codeForm").hidden = true; $("#authSeg").hidden = true; $("#resetForm").hidden = false; $("#authTitle").textContent = "Choose a new password"; $("#authSub").textContent = ""; }
$("#resetForm").onsubmit = async e => {
  e.preventDefault();
  const { error } = await SB.auth.updateUser({ password: $("#newpw").value });
  if (error) return setAuthMsg(error.message);
  history.replaceState(null, "", location.pathname); $("#authSeg").hidden = false; enter();
};
$("#useCode").onclick = e => { e.preventDefault(); $("#emailForm").hidden = $("#oauth").hidden = $("#orline").hidden = true; $("#codeForm").hidden = false; setAuthMsg(); };
$("#backToEmail").onclick = e => { e.preventDefault(); showAuth(); };
$("#codeForm").onsubmit = async e => {
  e.preventDefault(); store.set("ml_token", $("#code").value.trim());
  try { await enter(); } catch (err) { store.set("ml_token", null); setAuthMsg("That sign-in code wasn't recognised."); }
};
$("#signout").onclick = async () => { store.set("ml_token", null); if (SB) await SB.auth.signOut(); location.hash = ""; showAuth("signin"); };

// ---------- the app ----------
async function enter() {
  ME = await api("/v1/me");
  $("#auth").hidden = true; $("#appShell").hidden = false;
  $("#who").textContent = ME.email || "Signed in";
  $("#acctBtn").textContent = (ME.email || "M")[0].toUpperCase();
  drawBalance();
  if (!MODELS.length) MODELS = (await api("/v1/prices")).models.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  if (!C) setup();
  loadHistory(true);
}
function drawBalance() { $("#bal").textContent = money(ME.balance); $("#bal").classList.toggle("low", ME.balance < 1); }
async function refreshMe() { try { ME = await api("/v1/me"); drawBalance(); } catch {} }
document.querySelector(".top .tabs").onclick = e => { const b = e.target.closest("button"); if (b) show(b.dataset.view); };
function show(view) {
  document.querySelectorAll(".top .tabs button").forEach(x => x.classList.toggle("on", x.dataset.view === view));
  $("#work").hidden = view === "history"; $("#viewHistory").hidden = view !== "history";
  document.querySelectorAll("[data-pane]").forEach(p => p.hidden = p.dataset.pane !== view);
  store.set("ml_view", view);
  if (view === "history") drawHistory();
  if (view === "timeline") drawTimeline();
  if (view === "compare") drawCompare();
}
$("#acctBtn").onclick = e => { e.stopPropagation(); $("#acctMenu").hidden = !$("#acctMenu").hidden; };
document.addEventListener("click", () => $("#acctMenu").hidden = true);
function setup() {
  C = modelBox($("#cBox"), { key: "ml_model", change: () => { updateRun(); quoteSoon(); } });
  C.pick(byId(store.get("ml_model")) || MODELS.find(m => /flux.*schnell/.test(m.id)) || MODELS[0]);
  B = modelBox($("#bBox"), { key: "ml_bmodel", change: batchSoon });
  B.pick(byId(store.get("ml_bmodel")) || byId(store.get("ml_model")) || MODELS[0]);
  drawSteps(); drawWfList(); audioMode(AU_MODE);
  const v = store.get("ml_view"); if (v && v !== "create" && document.querySelector(`.top .tabs [data-view="${v}"]`)) show(v);
}

// ---------- choosing a model (one list, opened under whichever picker asked) ----------
const kind = m => /video/.test(m.cat) ? "video" : /audio|speech|music|sound|voice/.test(m.cat + m.id) ? "audio" : "image";
const unit = c => c.per === "run" ? "" : c.per === "clip" ? " / video" : c.per === "kchar" ? " / 1,000 characters" : ` / ${c.per}`;
const byId = id => MODELS.find(m => m.id === id);
let cat = "", dropFor = null;
function openDrop(picker, filter, done) {
  const d = $("#drop");
  if (!d.hidden && dropFor?.picker === picker) { d.hidden = true; return; }
  picker.append(d); dropFor = { picker, filter, done }; d.hidden = false;
  $("#msearch").value = ""; drawModels(); $("#msearch").focus();
}
function drawModels() {
  const q = $("#msearch").value.toLowerCase().split(/\s+/).filter(Boolean), f = dropFor?.filter;
  const list = MODELS.filter(m => (!f || f(m)) && (!cat || kind(m) === cat) && q.every(w => ((m.name || "") + " " + m.id + " " + m.cat).toLowerCase().includes(w))).slice(0, 120);
  $("#cats").hidden = !!f;
  $("#mlist").innerHTML = list.length ? list.map(m => `<div class="mrow" data-id="${esc(m.id)}">${m.thumb ? `<img src="${esc(m.thumb)}" alt="" loading="lazy">` : `<img alt="">`}<div><b>${esc(m.name || m.id)}</b><span>${esc(m.cat)}</span></div><span class="pr">${esc(money(m.cost.usd) + unit(m.cost))}</span></div>`).join("") : `<p class="muted" style="padding: 10px">No models match.</p>`;
}
$("#msearch").oninput = drawModels;
$("#cats").onclick = e => { const b = e.target.closest("button"); if (!b) return; cat = b.dataset.c; $("#cats").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); drawModels(); };
$("#mlist").onclick = e => { const r = e.target.closest(".mrow"); if (r) { $("#drop").hidden = true; dropFor.done(byId(r.dataset.id)); } };
document.addEventListener("click", e => { if (!e.target.closest(".picker")) $("#drop").hidden = true; });
const chosenHtml = m => m ? `<img src="${esc(m.thumb || "")}" alt=""${m.thumb ? "" : ` style="visibility: hidden"`}><div><b>${esc(m.name || m.id)}</b><span>${esc(m.cat)} · from ${money(m.cost.usd)}${unit(m.cost)}</span></div>`
  : `<img alt="" style="visibility: hidden"><div><b>Choose a model</b><span>Search over a thousand image, video and audio models</span></div>`;

// one model and its settings; Create, Batch, Audio and every workflow step each have one
const SCHEMAS = {};
const schemaOf = id => SCHEMAS[id] ||= api("/v1/schema?model=" + encodeURIComponent(id)).catch(e => { delete SCHEMAS[id]; throw e; });
function modelBox(root, o = {}) {
  root.innerHTML = `<div class="picker"><div class="chosen" tabindex="0">${chosenHtml()}</div></div><div class="form"></div>`;
  const box = { root, model: null, schema: null, values: {} }, form = root.querySelector(".form"), chosen = root.querySelector(".chosen");
  const changed = () => o.change?.(box);
  chosen.onclick = () => openDrop(chosen.parentNode, o.filter, m => box.pick(m));
  box.pick = async (m, values = {}) => {
    if (!m) return;
    Object.assign(box, { model: m, schema: null, values }); chosen.innerHTML = chosenHtml(m);
    if (o.key) store.set(o.key, m.id);
    form.innerHTML = `<p class="muted">Loading settings…</p>`; changed();
    try { box.schema = await schemaOf(m.id); } catch (e) { if (box.model === m) form.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    if (box.model === m) box.redraw();
  };
  box.redraw = () => { buildForm(form, box.schema, box.values, changed, o.chain); changed(); };
  box.missing = () => box.schema ? missing(box.schema, box.values) : ["a model"];
  return box;
}

// ---------- the settings form, built from the model's own schema ----------
const fileKind = (p, k = "") => p._fal_ui_field || (p.items && p.items._fal_ui_field) || ((/(^|_)image_urls?$/.test(k) && "image") || (/(^|_)video_urls?$/.test(k) && "video") || (/(^|_)audio_urls?$/.test(k) && "audio")) || null;
function buildForm(form, schema, values, changed, chain) {
  const props = schema.properties || {}, req = new Set(schema.required || []);
  const order = schema["x-fal-order-properties"] || Object.keys(props);
  const keys = order.filter(k => props[k] && fieldOk(props[k], k));
  const main = keys.filter(k => req.has(k) || /^(prompt|text)$/.test(k) || fileKind(props[k], k));
  const rest = keys.filter(k => !main.includes(k));
  form.innerHTML = main.map(k => field(k, props[k], req.has(k), values[k], chain)).join("") +
    (rest.length ? `<details class="more"><summary>More settings</summary><div class="form">${rest.map(k => field(k, props[k], false, values[k], chain)).join("")}</div></details>` : "");
  form.querySelectorAll("[data-k]").forEach(el => bind(el, values, changed));
}
function fieldOk(p, k) {
  if (fileKind(p, k)) return true;
  if (p.enum || ["string", "integer", "number", "boolean"].includes(p.type)) return true;
  return p.type === "array" && p.items && p.items.type === "string";
}
function label(k) { return k.replace(/_url(s?)$/, "$1").replace(/_/g, " ").replace(/^./, c => c.toUpperCase()); }
const PREV = "{{prev}}";
function field(k, p, required, v, chain) {
  const hint = p.description ? `<span class="hint">${esc(p.description.slice(0, 160))}</span>` : "";
  const name = `${esc(p.title || label(k))}${required ? " *" : ""}`;
  const fk = fileKind(p, k);
  if (fk) {
    const fromPrev = chain && [].concat(v ?? []).includes(PREV);
    return `<div class="field" data-k="${esc(k)}" data-file="${fk}" data-many="${p.type === "array" ? 1 : ""}"><label class="field">${name}${hint}</label>
      ${chain ? `<label class="toggle small"><input type="checkbox" data-prev ${fromPrev ? "checked" : ""}> Use the previous step's result</label>` : ""}
      <div class="files" ${fromPrev ? "hidden" : ""}>${fromPrev ? "" : [].concat(v ?? []).filter(u => u !== PREV).map(thumbHtml).join("")}<button type="button" class="add">＋ Add ${fk}</button></div><input type="file" accept="${fk}/*" ${p.type === "array" ? "multiple" : ""} hidden></div>`;
  }
  if (p.enum) return `<label class="field">${name}${hint}<select data-k="${esc(k)}">${required ? "" : `<option value="">Default${p.default != null ? ` (${esc(p.default)})` : ""}</option>`}${p.enum.map(o => `<option ${(v ?? (required ? p.default : undefined)) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
  if (p.type === "boolean") return `<label class="toggle"><input type="checkbox" data-k="${esc(k)}" ${(v ?? p.default) ? "checked" : ""}> ${name}</label>`;
  if (p.type === "integer" || p.type === "number") return `<label class="field">${name}${hint}<input type="number" data-k="${esc(k)}" value="${esc(v ?? "")}" ${p.minimum != null ? `min="${p.minimum}"` : ""} ${p.maximum != null ? `max="${p.maximum}"` : ""} step="${p.type === "integer" ? 1 : "any"}" placeholder="${p.default != null ? esc(p.default) : ""}"></label>`;
  if (p.type === "array") return `<label class="field">${name}<span class="hint">One per line</span><textarea data-k="${esc(k)}" data-lines="1" style="min-height: 70px">${esc((v || []).join("\n"))}</textarea></label>`;
  const big = /prompt|^text$|script|lyrics/.test(k);
  return big ? `<label class="field">${name}${hint}<textarea data-k="${esc(k)}" placeholder="${esc(p.default || "")}">${esc(v ?? "")}</textarea></label>`
             : `<label class="field">${name}${hint}<input data-k="${esc(k)}" value="${esc(v ?? "")}" placeholder="${esc(p.default ?? "")}"></label>`;
}
const thumbHtml = u => `<div class="thumb" data-u="${esc(u)}">${isVideo(u) ? `<video src="${esc(u)}#t=0.1" muted preload="metadata"></video>` : isAudio(u) ? `<span class="fname">${esc(u.split("/").pop().split("?")[0])}</span>` : `<img src="${esc(u)}" alt="">`}<button type="button" title="Remove">✕</button></div>`;
function bind(el, values, changed) {
  const k = el.dataset.k;
  if (el.dataset.file) {
    const input = el.querySelector("input[type=file]"), box = el.querySelector(".files"), many = !!el.dataset.many;
    const remove = t => t.querySelector("button").onclick = () => { const u = t.dataset.u; t.remove(); if (many) values[k] = (values[k] || []).filter(x => x !== u); else delete values[k]; if (!values[k]?.length) delete values[k]; changed(); };
    box.querySelectorAll(".thumb").forEach(remove);
    el.querySelector(".add").onclick = () => input.click();
    input.onchange = async () => {
      for (const f of input.files) {
        const t = document.createElement("div"); t.className = "thumb";
        const local = URL.createObjectURL(f);
        t.innerHTML = f.type.startsWith("video") ? `<video src="${local}" muted></video>` : f.type.startsWith("image") ? `<img src="${local}" alt="">` : `<span class="fname">${esc(f.name)}</span>`;
        box.prepend(t);
        try {
          const u = await upload(f); t.dataset.u = u;
          if (many) (values[k] ||= []).push(u); else { box.querySelectorAll(".thumb").forEach(x => x !== t && x.remove()); values[k] = u; }
          t.insertAdjacentHTML("beforeend", `<button type="button" title="Remove">✕</button>`); remove(t); changed();
        } catch (e) { t.remove(); toast(e.message); }
      }
      input.value = "";
    };
    const prev = el.querySelector("[data-prev]");
    if (prev) prev.onchange = () => {
      box.hidden = prev.checked; box.querySelectorAll(".thumb").forEach(t => t.remove());
      if (prev.checked) values[k] = many ? [PREV] : PREV; else delete values[k];
      changed();
    };
    return;
  }
  const set = () => {
    let v = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "number") v = v === "" ? undefined : Number(v);
    else if (el.dataset.lines) v = v.split("\n").map(s => s.trim()).filter(Boolean);
    if (v === "" || v === undefined || (Array.isArray(v) && !v.length)) delete values[k]; else values[k] = v;
    changed();
  };
  el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", set);
  if (el.tagName === "TEXTAREA" && !el.dataset.lines) el.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) el.closest(".panel")?.querySelector(".runbar .btn.primary")?.click(); });
  if (el.tagName === "SELECT" && el.value && values[k] == null) set();
}
async function upload(f) {
  const type = f.type || "application/octet-stream";
  try {
    const up = await api("/v1/uploads", { file_name: f.name, content_type: type });
    const r = await fetch(up.upload_url, { method: "PUT", body: f, headers: { "Content-Type": type } });
    if (!r.ok) throw new Error("The upload didn't go through. Try again.");
    return up.file_url;
  } catch (e) { throw e.status === 402 ? new Error("Top up your balance to upload files.") : e; }
}
const missing = (schema, values) => (schema.required || []).filter(k => values[k] == null && (schema.properties[k] || {}).default == null);
const promptKey = s => { const k = Object.keys(s.properties || {}); return k.find(x => /^(prompt|text)$/.test(x)) || k.find(x => /prompt/.test(x)); };
const fileKey = (s, want) => Object.entries(s.properties || {}).find(([k, p]) => fileKind(p, k) === want)?.[0];

// ---------- prices and runs ----------
// open models: the supplier the user chose for each model (blank = best price)
const pref = id => store.get("ml_sup:" + id) || "";
async function quote(id, input) {
  try { return await api("/v1/quote", { model: id, input, provider: pref(id) || undefined }); }
  catch (e) {
    if (e.status !== 409 || !pref(id)) throw e;
    store.set("ml_sup:" + id, null); toast(e.message + " Switched to Best price.", 6000);
    return api("/v1/quote", { model: id, input });
  }
}
// starts a run, shows it under Latest, and resolves when it's finished (done, failed or cancelled)
async function launch(model, input, note) {
  const item = { id: null, status: "submitting", model, input: { ...input }, note, created: Date.now() / 1000 };
  LATEST.unshift(item); drawLatest();
  try {
    const r = await api("/v1/runs", { model, input, provider: pref(model) || undefined });
    Object.assign(item, { id: r.id, status: "running", charged: r.charged });
    ME.balance -= r.charged; drawBalance(); drawLatest();
  } catch (e) {
    LATEST.splice(LATEST.indexOf(item), 1); drawLatest();
    if (e.status === 402) openTopup();
    throw e;
  }
  return watch(item);
}
async function watch(item) {
  while (item.status === "running" || item.status === "submitting") {
    await new Promise(r => setTimeout(r, 2500));
    try { Object.assign(item, await api("/v1/runs/" + item.id)); } catch {}
    drawLatest();
  }
  if (item.status !== "done") refreshMe();  // refunded
  if (!HIST.some(h => h.id === item.id)) HIST.unshift(item);
  return item;
}
// {{name}} in a later step: the whole value when it's all the box holds (a file, or every result for prev_all), else written into the text
function fillVars(v, vars) {
  if (typeof v === "string") {
    const m = v.trim().match(/^\{\{(\w+)\}\}$/);
    if (m && m[1] in vars) return vars[m[1]];
    return v.replace(/\{\{(\w+)\}\}/g, (x, n) => n in vars ? String(vars[n]) : x);
  }
  if (Array.isArray(v)) return v.flatMap(x => { const f = fillVars(x, vars); return Array.isArray(f) && !Array.isArray(x) ? f : [f]; });
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, fillVars(x, vars)]));
  return v;
}
// steps in order, each fed the one before ({{prev}}, {{prev_all}}) or any earlier step by its id ({{cut1}})
async function chain(steps, name) {
  const vars = {};
  for (const [i, st] of steps.entries()) {
    const item = await launch(st.model, fillVars(st.input, vars), steps.length > 1 ? `${name} · step ${i + 1} of ${steps.length}` : name);
    if (item.status !== "done" || !item.outputs?.length) throw new Error(`${name}: step ${i + 1} didn't work${item.error ? ": " + item.error : ""}. You weren't charged for it.`);
    vars.prev = item.outputs[0]; vars.prev_all = item.outputs;
    if (st.id) vars[st.id] = item.outputs[0];
  }
  return vars.prev;
}

// ---------- Create ----------
let C, B;
function updateRun() {
  const m = C.missing();
  $("#run").disabled = !C.model || m.length > 0;
  $("#run").title = m.length ? "Fill in: " + m.map(label).join(", ") : "";
}
$("#supSel").onchange = () => { store.set("ml_sup:" + C.model.id, $("#supSel").value || null); quoteSoon(); };
let qTimer;
function quoteSoon() {
  clearTimeout(qTimer);
  if ($("#supplier").dataset.model !== C.model?.id) $("#supplier").hidden = true;
  qTimer = setTimeout(async () => {
    if (!C.schema) return;
    try {
      const q = await quote(C.model.id, C.values);
      $("#price").textContent = "This run: " + money(q.price) + (q.hosted ? ` · run by ${q.provider_name}` : "");
      $("#run").textContent = "Run · " + money(q.price);
      $("#supplier").hidden = !q.choices; $("#supplier").dataset.model = C.model.id;
      if (q.choices) $("#supSel").innerHTML = `<option value="">Best price (${money(q.choices[0].price)})</option>` +
        q.choices.map(c => `<option value="${esc(c.id)}" ${c.id === pref(C.model.id) ? "selected" : ""}>${esc(c.name)} · ${money(c.price)}</option>`).join("");
    } catch { $("#price").textContent = ""; $("#run").textContent = "Run"; }
  }, 350);
}
$("#run").onclick = async () => {
  if ($("#run").disabled) return;
  $("#run").disabled = true;
  const done = launch(C.model.id, C.values).catch(e => toast(e.message, 6000));
  setTimeout(updateRun, 600); await done;
};
$("#toWf").onclick = () => {
  if (!C.model) return;
  WF.steps.push({ model: C.model.id, values: JSON.parse(JSON.stringify(C.values)) }); saveWf(); drawSteps();
  toast(`Added as step ${WF.steps.length} in Workflows.`);
};

// ---------- Batch: one model, many versions ----------
const bLines = () => $("#bLines").value.split("\n").map(s => s.trim()).filter(Boolean);
function batchInputs() {
  const lines = bLines(), copies = Math.min(10, Math.max(1, Math.round(+$("#bCopies").value || 1)));
  const uses = JSON.stringify(B.values).includes("{{line}}"), pk = promptKey(B.schema || {});
  if (lines.length && !uses && !pk) throw new Error("This model has no prompt box: put {{line}} in the box each line should go into.");
  const base = lines.length ? lines.map(line => uses ? fillVars(B.values, { line }) : { ...B.values, [pk]: line }) : [B.values];
  return base.flatMap(v => Array(copies).fill(v));
}
let bTimer;
function batchSoon() {
  clearTimeout(bTimer);
  bTimer = setTimeout(async () => {
    $("#bRun").disabled = true; $("#bPrice").textContent = "";
    if (!B.schema) return;
    let runs; try { runs = batchInputs(); } catch (e) { $("#bPrice").textContent = e.message; return; }
    const m = missing(B.schema, runs[0]);
    if (m.length) { $("#bPrice").textContent = "Fill in: " + m.map(label).join(", "); return; }
    if (runs.length > 50) { $("#bPrice").textContent = `${runs.length} runs: the most at once is 50.`; return; }
    try { const q = await quote(B.model.id, runs[0]); $("#bPrice").textContent = `${runs.length} ${runs.length === 1 ? "run" : "runs"} · about ${money(q.price * runs.length)}`; } catch {}
    $("#bRun").disabled = false; $("#bRun").textContent = `Run ${runs.length}`;
  }, 400);
}
$("#bLines").oninput = $("#bCopies").oninput = batchSoon;
$("#bRun").onclick = async () => {
  let runs; try { runs = batchInputs(); } catch (e) { return toast(e.message); }
  if (runs.length > 10 && !confirm(`This starts ${runs.length} runs (${$("#bPrice").textContent.split("· ")[1] || "each one charged"}). Continue?`)) return;
  $("#bRun").disabled = true;
  const results = await Promise.allSettled(runs.map((v, i) => launch(B.model.id, v, `Batch ${i + 1} of ${runs.length}`)));
  const failed = results.find(r => r.status === "rejected");
  if (failed) toast(failed.reason.message, 6000);
  batchSoon();
};

// ---------- Compare: one idea on several models ----------
let CMP = JSON.parse(store.get("ml_cmp") || "[]"), CMP_IMGS = [];
const saveCmp = () => store.set("ml_cmp", JSON.stringify(CMP));
// what each model gets: the prompt in its prompt box, the images in its image box
function cmpInput(s) {
  const v = {}, pk = promptKey(s), ik = fileKey(s, "image"), prompt = $("#cmpPrompt").value.trim();
  if (pk && prompt) v[pk] = prompt;
  if (ik && CMP_IMGS.length) v[ik] = s.properties[ik].type === "array" ? [...CMP_IMGS] : CMP_IMGS[0];
  return v;
}
let cmpTimer;
function drawCompare() {
  $("#cmpModels").innerHTML = CMP.length ? CMP.map(id => `<div class="cmprow" data-id="${esc(id)}"><span class="grow"><b>${esc(byId(id)?.name || id)}</b><span class="cmpstate muted">…</span></span><button class="btn small ghost" title="Remove">✕</button></div>`).join("")
    : `<p class="muted">Add two or more models to compare.</p>`;
  clearTimeout(cmpTimer);
  cmpTimer = setTimeout(async () => {
    let total = 0, ready = 0;
    for (const row of $("#cmpModels").querySelectorAll(".cmprow")) {
      const st = row.querySelector(".cmpstate");
      try {
        const s = await schemaOf(row.dataset.id), v = cmpInput(s), m = missing(s, v);
        if (m.length) { st.textContent = "Needs " + m.map(label).join(", "); row.dataset.ok = ""; continue; }
        const q = await quote(row.dataset.id, v); total += q.price; ready++;
        st.textContent = money(q.price); row.dataset.ok = 1;
      } catch (e) { st.textContent = e.message; row.dataset.ok = ""; }
    }
    $("#cmpPrice").textContent = ready ? `${ready} ${ready === 1 ? "model" : "models"} · ${money(total)}` : "";
    $("#cmpRun").disabled = !ready;
  }, 400);
}
$("#cmpModels").onclick = e => { const b = e.target.closest("button"); if (!b) return; CMP = CMP.filter(id => id !== b.closest(".cmprow").dataset.id); saveCmp(); drawCompare(); };
$("#cmpAdd").onclick = () => openDrop($("#cmpPick"), null, m => { if (!CMP.includes(m.id)) CMP.push(m.id); saveCmp(); drawCompare(); });
$("#cmpPrompt").oninput = drawCompare;
$("#cmpImgAdd").onclick = () => $("#cmpFile").click();
$("#cmpFile").onchange = async () => {
  for (const f of $("#cmpFile").files) { try { CMP_IMGS.push(await upload(f)); } catch (e) { toast(e.message); } }
  $("#cmpFile").value = ""; drawCmpImgs(); drawCompare();
};
function drawCmpImgs() {
  $("#cmpImgs").querySelectorAll(".thumb").forEach(t => t.remove());
  $("#cmpImgAdd").insertAdjacentHTML("beforebegin", CMP_IMGS.map(thumbHtml).join(""));
  $("#cmpImgs").querySelectorAll(".thumb button").forEach(b => b.onclick = () => { CMP_IMGS = CMP_IMGS.filter(u => u !== b.parentNode.dataset.u); drawCmpImgs(); drawCompare(); });
}
$("#cmpRun").onclick = async () => {
  $("#cmpRun").disabled = true;
  const rows = [...$("#cmpModels").querySelectorAll('.cmprow[data-ok="1"]')];
  const results = await Promise.allSettled(rows.map(async r => launch(r.dataset.id, cmpInput(await schemaOf(r.dataset.id)), "Compare")));
  const failed = results.find(r => r.status === "rejected");
  if (failed) toast(failed.reason.message, 6000);
  drawCompare();
};

// ---------- Workflows: steps chained together ----------
let WF = JSON.parse(store.get("ml_wf") || '{"name": "", "steps": []}');
// ponytail: saved workflows live in this browser; phase 2 moves them into the account with the Library
let WF_SAVED = JSON.parse(store.get("ml_workflows") || "{}");
const saveWf = () => store.set("ml_wf", JSON.stringify(WF));
let STEP_BOXES = [];
function drawSteps() {
  const list = $("#wfSteps"); list.innerHTML = ""; STEP_BOXES = [];
  if (!WF.steps.length) list.innerHTML = `<p class="muted">No steps yet. Add one below, or use “＋ Workflow step” on the Create tab.</p>`;
  WF.steps.forEach((st, i) => {
    const card = document.createElement("div"); card.className = "step";
    card.innerHTML = `<div class="stephead"><b>Step ${i + 1}</b><span class="grow"></span><button class="btn small ghost" data-a="up" title="Move up">↑</button><button class="btn small ghost" data-a="down" title="Move down">↓</button><button class="btn small ghost" data-a="del" title="Remove">✕</button></div><div></div>`;
    card.querySelector(".stephead").onclick = e => {
      const a = e.target.closest("[data-a]")?.dataset.a; if (!a) return;
      if (a === "up" && i) [WF.steps[i - 1], WF.steps[i]] = [st, WF.steps[i - 1]];
      if (a === "down" && i < WF.steps.length - 1) [WF.steps[i + 1], WF.steps[i]] = [st, WF.steps[i + 1]];
      if (a === "del") WF.steps.splice(i, 1);
      saveWf(); drawSteps();
    };
    list.append(card);
    const box = modelBox(card.lastElementChild, { chain: i > 0, change: b => { st.model = b.model?.id; st.values = b.values; saveWf(); wfSoon(); } });
    STEP_BOXES.push(box);
    if (st.model) box.pick(byId(st.model), st.values || {});
  });
  $("#wfName").value = WF.name || "";
  wfSoon();
}
$("#wfAdd").onclick = () => { WF.steps.push({ model: null, values: {} }); saveWf(); drawSteps(); setTimeout(() => STEP_BOXES.at(-1).root.querySelector(".chosen").click()); };
let wfTimer;
function wfSoon() {
  clearTimeout(wfTimer);
  wfTimer = setTimeout(async () => {
    $("#wfRun").disabled = true; $("#wfPrice").textContent = "";
    if (!WF.steps.length) return;
    const gaps = STEP_BOXES.map((b, i) => b.missing().length ? `step ${i + 1} needs ${b.missing().map(label).join(", ")}` : "").filter(Boolean);
    if (gaps.length) { $("#wfPrice").textContent = gaps[0][0].toUpperCase() + gaps[0].slice(1); return; }
    $("#wfRun").disabled = false;
    try {  // later steps are priced with a stand-in for the earlier result; the exact price is charged as each one starts
      const sample = "https://v3.fal.media/files/sample/sample.png";
      const qs = await Promise.all(STEP_BOXES.map(b => quote(b.model.id, fillVars(b.values, { prev: sample, prev_all: [sample] }))));
      $("#wfPrice").textContent = `${WF.steps.length} ${WF.steps.length === 1 ? "step" : "steps"} · about ${money(qs.reduce((a, q) => a + q.price, 0))}`;
    } catch { $("#wfPrice").textContent = "Each step is priced when it starts"; }
  }, 400);
}
$("#wfRun").onclick = async () => {
  $("#wfRun").disabled = true;
  try { await chain(WF.steps.map(s => ({ model: s.model, input: s.values })), WF.name || "Workflow"); toast("Workflow finished."); }
  catch (e) { toast(e.message, 7000); }
  finally { wfSoon(); }
};
function drawWfList() {
  const names = Object.keys(WF_SAVED).sort();
  $("#wfList").innerHTML = names.length ? names.map(n => `<option>${esc(n)}</option>`).join("") : `<option value="">No saved workflows</option>`;
}
$("#wfSave").onclick = () => {
  const name = $("#wfName").value.trim(); if (!name) return toast("Give the workflow a name.");
  if (!WF.steps.length) return toast("Add a step first.");
  if (WF_SAVED[name] && !confirm(`Replace the saved workflow “${name}”?`)) return;
  WF.name = name; WF_SAVED[name] = JSON.parse(JSON.stringify(WF.steps));
  store.set("ml_workflows", JSON.stringify(WF_SAVED)); saveWf(); drawWfList(); $("#wfList").value = name; toast(`Saved “${name}”.`);
};
$("#wfOpen").onclick = () => {
  const name = $("#wfList").value; if (!name) return;
  if (WF.steps.length && !confirm(`Replace the current steps with “${name}”?`)) return;
  WF = { name, steps: JSON.parse(JSON.stringify(WF_SAVED[name])) }; saveWf(); drawSteps();
};
$("#wfDel").onclick = () => {
  const name = $("#wfList").value; if (!name || !confirm(`Delete the saved workflow “${name}”?`)) return;
  delete WF_SAVED[name]; store.set("ml_workflows", JSON.stringify(WF_SAVED)); drawWfList();
};
$("#wfNew").onclick = () => { if (WF.steps.length && !confirm("Clear the current steps?")) return; WF = { name: "", steps: [] }; saveWf(); drawSteps(); };
$("#wfName").oninput = () => { WF.name = $("#wfName").value; saveWf(); };

// ---------- Audio: voice, music, sound effects, lip sync ----------
const AU_MODES = {
  voice: { hint: "Type what should be said. Pick a voice under More settings.", test: m => m.cat === "text-to-speech",
           prefer: ["fal-ai/elevenlabs/tts/eleven-v3", "fal-ai/elevenlabs/tts/multilingual-v2", "fal-ai/minimax/speech-02-hd", "fal-ai/index-tts-2/text-to-speech"] },
  music: { hint: "Describe the song: genre, mood, instruments, tempo.", test: m => /audio/.test(m.cat) && /music|song|lyria|ace-step|instrumental/.test(m.id),
           prefer: ["fal-ai/elevenlabs/music", "elevenlabs/music/v2", "fal-ai/minimax-music/v2", "google/lyria-3.5"] },
  sfx: { hint: "Describe the sound, e.g. “glass shattering in a large hall”.", test: m => /audio/.test(m.cat) && /sound|sfx|effect|mmaudio/.test(m.id),
         prefer: ["fal-ai/elevenlabs/sound-effects/v2", "mirelo-ai/sfx2.0/text-to-audio", "fal-ai/mmaudio-v2/text-to-audio"] },
  lipsync: { hint: "A video of a face plus a voice or song: the mouth moves to the audio.", test: m => /lipsync/.test(m.id),
             prefer: ["fal-ai/sync-lipsync/v3", "fal-ai/sync-lipsync/v2", "veed/lipsync"] },
};
let AU_MODE = store.get("ml_au") || "voice", AU;
function audioMode(mode) {
  AU_MODE = AU_MODES[mode] ? mode : "voice"; store.set("ml_au", AU_MODE);
  const M = AU_MODES[AU_MODE];
  $("#auMode").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.m === AU_MODE));
  $("#auHint").textContent = M.hint;
  AU = modelBox($("#auBox"), { key: "ml_au_" + AU_MODE, filter: M.test, change: auSoon });
  AU.pick(byId(store.get("ml_au_" + AU_MODE)) || M.prefer.map(byId).find(Boolean) || MODELS.find(M.test));
}
$("#auMode").onclick = e => { const b = e.target.closest("button"); if (b) audioMode(b.dataset.m); };
let auTimer;
function auSoon() {
  clearTimeout(auTimer);
  auTimer = setTimeout(async () => {
    const m = AU.missing(); $("#auRun").disabled = m.length > 0; $("#auPrice").textContent = m.length && AU.schema ? "Fill in: " + m.map(label).join(", ") : "";
    if (m.length) return;
    try { const q = await quote(AU.model.id, AU.values); $("#auPrice").textContent = "This run: " + money(q.price); } catch {}
  }, 350);
}
$("#auRun").onclick = () => { $("#auRun").disabled = true; launch(AU.model.id, AU.values, $("#auMode .on").textContent).catch(e => toast(e.message, 6000)).finally(auSoon); };

// ---------- Timeline: clips in order, a soundtrack, one exported film ----------
let TL = JSON.parse(store.get("ml_timeline") || '{"clips": [], "audio": ""}');
const saveTL = () => store.set("ml_timeline", JSON.stringify(TL));
const outputs = test => [...new Set(HIST.filter(r => r.status === "done").flatMap(r => r.outputs || []).filter(test))].slice(0, 60);
const fname = u => decodeURIComponent(u.split("?")[0].split("/").pop());
function drawTimeline() {
  const songs = outputs(isAudio);
  $("#tlBody").innerHTML = `<p class="intro">Put your clips in order, add a song or voice-over, preview it, and export one video. Use <b>Add to Timeline</b> on any video in History, or add them here.</p>
    <video id="tlPlayer" controls playsinline></video>
    <div class="row"><button class="btn small" id="tlPlay">▶ Play the whole film</button><span class="muted" id="tlInfo"></span></div>
    <div class="clips" id="tlClips"></div>
    <div class="row"><button class="btn small" id="tlAdd">＋ Add from your creations</button><button class="btn small" id="tlUp">Upload a clip</button><input type="file" id="tlFile" accept="video/*" multiple hidden></div>
    <div class="pickgrid" id="tlPick" hidden></div>
    <label class="field">Soundtrack<span class="hint">Replaces the clips' own sound. Make music or a voice-over in the Audio tab and it shows up here.</span>
      <select id="tlAudio"><option value="">None, keep each clip's sound</option>${songs.map(u => `<option value="${esc(u)}"${u === TL.audio ? " selected" : ""}>${esc(fname(u))}</option>`).join("")}${TL.audio && !songs.includes(TL.audio) ? `<option value="${esc(TL.audio)}" selected>${esc(fname(TL.audio))}</option>` : ""}</select></label>
    <div class="row"><button class="btn small" id="tlAUp">Upload audio</button><input type="file" id="tlAFile" accept="audio/*" hidden></div>
    <div id="tlNotes"></div>
    <p class="hint">Exporting joins the clips on our servers for a few cents. Keep this page open while it exports.</p>
    <div class="runbar"><button class="btn small" id="tlCheck" title="Finds silent starts and ends, dead air, clips that run long, and mismatched sizes">✂ Check my cut</button><button class="btn primary" id="tlExport">Export the film</button></div>`;
  let total = 0;
  $("#tlClips").innerHTML = TL.clips.length ? "" : `<p class="muted">No clips yet.</p>`;
  TL.clips.forEach((c, i) => {
    const d = document.createElement("div"); d.className = "clip";
    d.innerHTML = `<b>${i + 1}</b><video src="${esc(c.url)}#t=0.1" muted preload="metadata" playsinline></video><span class="grow"><span class="muted dur"></span>
      <span class="trim">from <input type="number" min="0" step="0.1" value="${c.start ?? ""}" placeholder="0" data-t="start">s to <input type="number" min="0" step="0.1" value="${c.end ?? ""}" placeholder="end" data-t="end">s</span></span>
      <button class="btn small ghost" data-a="up">↑</button><button class="btn small ghost" data-a="down">↓</button><button class="btn small ghost" data-a="del">✕</button>`;
    const v = d.querySelector("video");
    d.querySelectorAll("[data-t]").forEach(x => x.onchange = () => { c[x.dataset.t] = x.value === "" ? null : Math.max(0, +x.value); saveTL(); drawTimeline(); });
    v.onloadedmetadata = () => { c.length = v.duration; const len = (c.end ?? v.duration) - (c.start || 0); d.querySelector(".dur").textContent = c.start || c.end != null ? `${len.toFixed(1)}s of ${v.duration.toFixed(1)}s` : v.duration.toFixed(1) + "s"; total += len; $("#tlInfo").textContent = `${TL.clips.length} clips · ${total.toFixed(1)}s`; };
    v.onclick = () => { const pl = $("#tlPlayer"); pl.src = c.url + `#t=${c.start || 0}${c.end != null ? "," + c.end : ""}`; pl.play(); };
    d.onclick = e => {
      const a = e.target.closest("[data-a]")?.dataset.a; if (!a) return;
      if (a === "up" && i) [TL.clips[i - 1], TL.clips[i]] = [c, TL.clips[i - 1]];
      if (a === "down" && i < TL.clips.length - 1) [TL.clips[i + 1], TL.clips[i]] = [c, TL.clips[i + 1]];
      if (a === "del") TL.clips.splice(i, 1);
      saveTL(); drawTimeline();
    };
    $("#tlClips").append(d);
  });
  $("#tlAdd").onclick = () => {
    const g = $("#tlPick"), vids = outputs(isVideo);
    g.hidden = !g.hidden;
    g.innerHTML = vids.length ? vids.map(u => `<video src="${esc(u)}#t=0.1" muted preload="metadata" playsinline data-u="${esc(u)}" title="Add this clip"></video>`).join("") : `<p class="muted">No videos in your creations yet.</p>`;
    g.querySelectorAll("video").forEach(v => v.onclick = () => { TL.clips.push({ url: v.dataset.u }); saveTL(); drawTimeline(); });
  };
  const up = async (input, done) => { for (const f of input.files) { try { done(await upload(f)); } catch (e) { toast(e.message); } } saveTL(); drawTimeline(); };
  $("#tlUp").onclick = () => $("#tlFile").click();
  $("#tlFile").onchange = () => up($("#tlFile"), url => TL.clips.push({ url }));
  $("#tlAUp").onclick = () => $("#tlAFile").click();
  $("#tlAFile").onchange = () => up($("#tlAFile"), url => TL.audio = url);
  $("#tlAudio").onchange = e => { TL.audio = e.target.value; saveTL(); };
  $("#tlPlay").onclick = () => {
    if (!TL.clips.length) return;
    const pl = $("#tlPlayer"); let k = 0; const track = TL.audio ? new Audio(TL.audio) : null;
    pl.muted = !!track;
    // each clip plays from its in-point to its out-point (the #t= range stops it there)
    const next = () => { if (k >= TL.clips.length) { track?.pause(); pl.onended = pl.onpause = null; return; } const c = TL.clips[k++]; pl.src = c.url + `#t=${c.start || 0}${c.end != null ? "," + c.end : ""}`; pl.play(); };
    pl.onended = next; pl.onpause = () => { if (!pl.ended && pl.currentTime >= (TL.clips[k - 1]?.end ?? Infinity) - 0.05) next(); }; next(); track?.play();
  };
  $("#tlCheck").onclick = checkCut;
  $("#tlExport").onclick = async () => {
    // trimmed clips are cut first (each its own step, referred to by id), then everything is joined
    const steps = [], vids = TL.clips.map((c, i) => {
      if (!c.start && c.end == null) return c.url;
      steps.push({ id: `cut${i + 1}`, model: "fal-ai/workflow-utilities/trim-video", input: { video_url: c.url, start_time: c.start || 0, ...(c.end != null ? { end_time: c.end } : { duration: Math.max(0.1, (c.length || 600) - (c.start || 0)) }) } });
      return `{{cut${i + 1}}}`;
    });
    if (vids.length > 1) steps.push({ model: "fal-ai/ffmpeg-api/merge-videos", input: { video_urls: vids } });
    if (TL.audio) steps.push({ model: "fal-ai/ffmpeg-api/merge-audio-video", input: { video_url: vids.length > 1 ? "{{prev}}" : vids[0], audio_url: TL.audio } });
    if (!steps.length) return toast("Add at least two clips, or one clip and a soundtrack.");
    const gone = steps.find(s => !byId(s.model));
    if (gone) return toast("Exporting isn't available right now. Please try again later.");
    $("#tlExport").disabled = true; toast("Exporting. The film appears under Latest when it's ready.");
    try { await chain(steps, "Timeline film"); toast("Your film is ready."); } catch (e) { toast(e.message, 7000); } finally { $("#tlExport").disabled = false; }
  };
}
// Check my cut: reads each clip's sound in the browser and flags what an editor would trim
async function clipFacts(c) {
  const v = document.createElement("video"); v.src = c.url; v.preload = "metadata"; v.muted = true;
  await new Promise(ok => { v.onloadedmetadata = ok; v.onerror = ok; });
  const facts = { duration: v.duration || 0, w: v.videoWidth, h: v.videoHeight, sound: null };
  try {
    const buf = await (await fetch(c.url)).arrayBuffer();
    const audio = await new (window.AudioContext || window.webkitAudioContext)().decodeAudioData(buf);
    const data = audio.getChannelData(0), win = Math.floor(audio.sampleRate * 0.05), loud = [];
    for (let i = 0; i + win <= data.length; i += win) { let sum = 0; for (let j = i; j < i + win; j++) sum += data[j] * data[j]; loud.push(20 * Math.log10(Math.sqrt(sum / win) + 1e-9) > -45); }
    facts.sound = loud;  // one flag per 50ms: is anything audible?
  } catch { facts.sound = null; }  // no audio track, or the file can't be read here
  return facts;
}
async function checkCut() {
  const box = $("#tlNotes"); if (!TL.clips.length) return;
  box.innerHTML = `<p class="muted">Listening to each clip…</p>`;
  const notes = [], sizes = new Set();
  for (const [i, c] of TL.clips.entries()) {
    const f = await clipFacts(c), a = c.start || 0, b = c.end ?? f.duration, n = i + 1;
    if (f.w) sizes.add(`${f.w}×${f.h}`);
    if (f.sound && !TL.audio) {
      const s = f.sound.slice(Math.floor(a / 0.05), Math.ceil(b / 0.05)), first = s.indexOf(true), last = s.lastIndexOf(true);
      if (first < 0) notes.push({ n, text: `Clip ${n} is silent.` });
      else {
        if (first * 0.05 >= 0.4) notes.push({ n, text: `Clip ${n} starts with ${(first * 0.05).toFixed(1)}s of silence. Start it on the action.`, fix: { start: +(a + first * 0.05 - 0.1).toFixed(1) } });
        const tail = (s.length - 1 - last) * 0.05;
        if (tail >= 0.4) notes.push({ n, text: `Clip ${n} ends with ${tail.toFixed(1)}s of silence. Pull the end in.`, fix: { end: +(a + (last + 1) * 0.05 + 0.15).toFixed(1) } });
        let run = 0, at = 0;
        for (let k = first; k <= last; k++) { if (!s[k]) { if (!run) at = k; run++; } else { if (run * 0.05 >= 0.8) notes.push({ n, text: `Clip ${n} goes quiet for ${(run * 0.05).toFixed(1)}s at ${(a + at * 0.05).toFixed(1)}s. Split there or trim around it.` }); run = 0; } }
      }
    }
    if (b - a > 6) notes.push({ n, text: `Clip ${n} runs ${(b - a).toFixed(1)}s. Short-form cuts land better at 1-4s; trim it to the strongest moment.` });
  }
  if (sizes.size > 1) notes.push({ text: `The clips are different sizes (${[...sizes].join(", ")}). They'll be letterboxed to match; make them in one shape for a cleaner film.` });
  box.innerHTML = notes.length ? notes.map((x, k) => `<div class="cutnote"><span class="grow">${esc(x.text)}</span>${x.fix ? `<button class="btn small" data-k="${k}">Apply</button>` : ""}</div>`).join("")
    : `<div class="cutnote ok">Nothing to flag. The cut is tight.</div>`;
  box.querySelectorAll("[data-k]").forEach(btn => btn.onclick = () => { const x = notes[+btn.dataset.k]; Object.assign(TL.clips[x.n - 1], x.fix); saveTL(); drawTimeline(); toast(`Clip ${x.n} trimmed.`); });
}

// ---------- results ----------
const ext = u => (u.split("?")[0].match(/\.(\w+)$/) || [])[1]?.toLowerCase() || "";
const isVideo = u => ["mp4", "webm", "mov", "m4v"].includes(ext(u)), isAudio = u => ["mp3", "wav", "ogg", "m4a", "flac", "aac"].includes(ext(u));
const mediaOf = u => isVideo(u) ? "video" : isAudio(u) ? "audio" : "image";
function mediaHtml(u, big) {
  if (isVideo(u)) return `<video src="${esc(u)}" ${big ? "controls autoplay loop" : "muted loop playsinline"}></video>`;
  if (isAudio(u)) return `<audio src="${esc(u)}" controls></audio>`;
  return `<img src="${esc(u)}" alt="" loading="lazy">`;
}
const promptText = run => (run.input && (run.input.prompt || run.input.text)) || "";
function tile(run) {
  const label = esc(promptText(run) || byId(run.model)?.name || run.model);
  if (run.status === "done" && run.outputs?.length) return `<div class="item" data-id="${esc(run.id)}">${mediaHtml(run.outputs[0])}${run.outputs.length > 1 ? `<span class="count">${run.outputs.length}</span>` : ""}<div class="meta"><span>${label}</span><span>${money(run.charged || 0)}</span></div></div>`;
  if (run.status === "failed" || run.status === "cancelled") return `<div class="item fail"><div class="state">${run.status === "failed" ? "This run didn't work" : "Cancelled"}. You weren't charged.<br><span class="muted">${esc((run.error || "").slice(0, 140))}</span></div></div>`;
  return `<div class="item wait"><div class="state">${run.note ? esc(run.note) + "<br>" : ""}${run.queue_position ? `In the queue · ${run.queue_position} ahead` : "Creating…"}</div></div>`;
}
function drawLatest() {
  const items = [...LATEST, ...HIST.filter(h => !LATEST.some(l => l.id === h.id))].slice(0, 12);
  $("#latest").innerHTML = items.length ? items.map(tile).join("") : `<div class="empty">Your creations will appear here.</div>`;
}
let hKind = "";
function drawHistory() {
  const q = $("#hSearch").value.toLowerCase().split(/\s+/).filter(Boolean);
  const list = HIST.filter(r => (!hKind || (r.outputs?.length && mediaOf(r.outputs[0]) === hKind)) && q.every(w => (promptText(r) + " " + (byId(r.model)?.name || "") + " " + r.model).toLowerCase().includes(w)));
  $("#historyGrid").innerHTML = list.length ? list.map(tile).join("") : `<div class="empty">${HIST.length ? "Nothing matches." : "Nothing yet: make something on the Create tab."}</div>`;
  $("#more").hidden = HIST_DONE || !HIST.length;
}
$("#hSearch").oninput = drawHistory;
$("#hKind").onclick = e => { const b = e.target.closest("button"); if (!b) return; hKind = b.dataset.c; $("#hKind").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); drawHistory(); };
async function loadHistory(fresh) {
  const before = fresh ? "" : (HIST[HIST.length - 1]?.created || "");
  try {
    const { runs } = await api("/v1/runs?limit=60" + (before ? "&before=" + before : ""));
    HIST = fresh ? runs : HIST.concat(runs); HIST_DONE = runs.length < 60;
    HIST.filter(r => r.status === "running" || r.status === "submitting").forEach(watch);
  } catch {}
  drawLatest(); if (!$("#viewHistory").hidden) drawHistory();
}
$("#more").onclick = () => loadHistory(false);
document.addEventListener("click", e => {
  const it = e.target.closest(".item[data-id]"); if (!it) return;
  const run = [...LATEST, ...HIST].find(r => r.id === it.dataset.id); if (run) openViewer(run);
});
function openViewer(run, at = 0) {
  const u = run.outputs[at], kindOf = mediaOf(u), prompt = promptText(run);
  $("#vMedia").innerHTML = mediaHtml(u, true);
  $("#vSide").innerHTML = `<b style="font-size: 16px">${esc(byId(run.model)?.name || run.model)}</b>
    ${prompt ? `<div class="prompt">${esc(prompt)}</div>` : ""}
    <span class="muted">${new Date(run.created * 1000).toLocaleString()} · ${money(run.charged || 0)}${run.provider_name ? ` · run by ${esc(run.provider_name)}` : ""}</span>
    ${run.outputs.length > 1 ? `<div class="strip">${run.outputs.map((o, i) => `<button class="${i === at ? "on" : ""}" data-i="${i}">${isAudio(o) ? "♪" : isVideo(o) ? `<video src="${esc(o)}#t=0.1" muted preload="metadata"></video>` : `<img src="${esc(o)}" alt="">`}</button>`).join("")}</div>` : ""}
    <div class="row"><a class="btn small primary" href="${esc(u)}" target="_blank" rel="noopener" download>Download</a>
    <button class="btn small" id="vAgain">Use these settings</button><button class="btn small" id="vInput">Use as input</button>
    ${kindOf === "video" ? `<button class="btn small" id="vClip">Add to Timeline</button>` : ""}${kindOf === "audio" ? `<button class="btn small" id="vSong">Use as soundtrack</button>` : ""}
    <button class="btn small" id="vDelete">Delete</button><button class="btn small ghost" id="vClose">Close</button></div>`;
  $("#viewer").hidden = false;
  $("#vSide").querySelectorAll(".strip button").forEach(b => b.onclick = () => openViewer(run, +b.dataset.i));
  $("#vClose").onclick = () => { $("#viewer").hidden = true; $("#vMedia").innerHTML = ""; };
  $("#vAgain").onclick = () => { $("#vClose").click(); show("create"); C.pick(byId(run.model) || { id: run.model, name: run.model, cat: "", cost: { usd: 0, per: "run" } }, JSON.parse(JSON.stringify(run.input || {}))); };
  $("#vInput").onclick = () => {
    $("#vClose").click(); show("create");
    const k = C.schema && fileKey(C.schema, kindOf);
    if (!k) return toast(`${C.model?.name || "This model"} doesn't take ${kindOf === "image" ? "an image" : "a" + (kindOf === "audio" ? "n audio file" : " video")}. Choose one that does, then try again.`, 6000);
    C.values[k] = C.schema.properties[k].type === "array" ? [...(C.values[k] || []), u] : u; C.redraw(); toast("Added to " + label(k) + ".");
  };
  if ($("#vClip")) $("#vClip").onclick = () => { TL.clips.push({ url: u }); saveTL(); toast(`Added to the Timeline (clip ${TL.clips.length}).`); };
  if ($("#vSong")) $("#vSong").onclick = () => { TL.audio = u; saveTL(); toast("Set as the Timeline's soundtrack."); };
  $("#vDelete").onclick = async () => {
    if (!confirm("Delete this from your history? This can't be undone.")) return;
    try { await api(`/v1/runs/${run.id}/delete`, {}); HIST = HIST.filter(r => r.id !== run.id); LATEST = LATEST.filter(r => r.id !== run.id); $("#vClose").click(); drawLatest(); drawHistory(); } catch (e) { toast(e.message); }
  };
}
$("#viewer").onclick = e => { if (e.target.id === "viewer") $("#vClose").click(); };

// ---------- top-ups ----------
function openTopup() { $("#topup").hidden = false; $("#topErr").hidden = true; }
$("#bal").onclick = openTopup; $("#topupMenu").onclick = openTopup;
$("#topClose").onclick = () => $("#topup").hidden = true;
$("#topup").onclick = e => { if (e.target.id === "topup") $("#topup").hidden = true; };
$("#amounts").onclick = e => { const b = e.target.closest("button"); if (b) { $("#amt").value = b.dataset.a; $("#topGo").click(); } };
$("#topGo").onclick = async () => {
  const amount = Math.round(+$("#amt").value);
  if (!amount) { $("#topErr").hidden = false; $("#topErr").textContent = "Pick an amount."; return; }
  try {
    const { checkout_url } = await api("/v1/topups", { amount });
    window.open(checkout_url, "_blank", "noopener");
    $("#topup").hidden = true; toast("Checkout opened in a new tab. Your balance updates here when it's paid.", 6000);
    const before = ME.balance;
    for (let i = 0; i < 60 && ME.balance <= before; i++) { await new Promise(r => setTimeout(r, 5000)); await refreshMe(); }
  } catch (e) { $("#topErr").hidden = false; $("#topErr").textContent = e.message; }
};

boot();
