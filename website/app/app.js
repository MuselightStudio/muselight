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

let CFG = {}, ON = null, SB = null, ME = null, MODELS = [], MODEL = null, SCHEMA = null, VALUES = {}, LATEST = [], HIST = [], HIST_DONE = false, mode = "signup";

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
  setAuthMsg();
}
function telegramButton() {
  const box = $("#tgbox"); box.innerHTML = "";
  if (!CFG.telegram_bot) return;
  const s = document.createElement("script");
  s.async = true; s.src = "https://telegram.org/js/telegram-widget.js?22";
  s.dataset.telegramLogin = CFG.telegram_bot; s.dataset.size = "large"; s.dataset.radius = "12"; s.dataset.requestAccess = "";
  s.dataset.authUrl = location.origin + location.pathname;  // Telegram sends people back here with a signed login
  box.append(s);
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
  if (!MODEL) { const last = store.get("ml_model"); pickModel(MODELS.find(m => m.id === last) || MODELS.find(m => /flux.*schnell/.test(m.id)) || MODELS[0]); }
  loadHistory(true);
}
function drawBalance() { $("#bal").textContent = money(ME.balance); $("#bal").classList.toggle("low", ME.balance < 1); }
async function refreshMe() { try { ME = await api("/v1/me"); drawBalance(); } catch {} }
document.querySelector(".top .tabs").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll(".top .tabs button").forEach(x => x.classList.toggle("on", x === b));
  $("#viewCreate").hidden = b.dataset.view !== "create"; $("#viewHistory").hidden = b.dataset.view !== "history";
  if (b.dataset.view === "history") drawHistory();
};
$("#acctBtn").onclick = e => { e.stopPropagation(); $("#acctMenu").hidden = !$("#acctMenu").hidden; };
document.addEventListener("click", () => $("#acctMenu").hidden = true);

// ---------- choosing a model ----------
const kind = m => /video/.test(m.cat) ? "video" : /audio|speech|music|sound|voice/.test(m.cat + m.id) ? "audio" : "image";
const unit = c => c.per === "run" ? "" : c.per === "clip" ? " / video" : ` / ${c.per}`;
let cat = "";
function drawModels() {
  const q = $("#msearch").value.toLowerCase().split(/\s+/).filter(Boolean);
  const list = MODELS.filter(m => (!cat || kind(m) === cat) && q.every(w => ((m.name || "") + " " + m.id + " " + m.cat).toLowerCase().includes(w))).slice(0, 120);
  $("#mlist").innerHTML = list.length ? list.map(m => `<div class="mrow" data-id="${esc(m.id)}">${m.thumb ? `<img src="${esc(m.thumb)}" alt="" loading="lazy">` : `<img alt="">`}<div><b>${esc(m.name || m.id)}</b><span>${esc(m.cat)}</span></div><span class="pr">${esc(money(m.cost.usd) + unit(m.cost))}</span></div>`).join("") : `<p class="muted" style="padding: 10px">No models match.</p>`;
}
$("#chosen").onclick = () => { $("#drop").hidden = !$("#drop").hidden; if (!$("#drop").hidden) { drawModels(); $("#msearch").focus(); } };
$("#msearch").oninput = drawModels;
$("#cats").onclick = e => { const b = e.target.closest("button"); if (!b) return; cat = b.dataset.c; $("#cats").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); drawModels(); };
$("#mlist").onclick = e => { const r = e.target.closest(".mrow"); if (r) { pickModel(MODELS.find(m => m.id === r.dataset.id)); $("#drop").hidden = true; } };
document.addEventListener("click", e => { if (!e.target.closest("#picker")) $("#drop").hidden = true; });

async function pickModel(m) {
  if (!m) return;
  MODEL = m; store.set("ml_model", m.id); VALUES = {};
  $("#chosenName").textContent = m.name || m.id;
  $("#chosenMeta").textContent = `${m.cat} · from ${money(m.cost.usd)}${unit(m.cost)}`;
  $("#chosenImg").src = m.thumb || ""; $("#chosenImg").style.visibility = m.thumb ? "" : "hidden";
  $("#form").innerHTML = `<p class="muted">Loading settings…</p>`; $("#run").disabled = true; $("#price").textContent = ""; $("#supplier").hidden = true;
  try { SCHEMA = await api("/v1/schema?model=" + encodeURIComponent(m.id)); } catch (e) { $("#form").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  drawForm(); quoteSoon();
}

// ---------- the settings form, built from the model's own schema ----------
const fileKind = p => p._fal_ui_field || (p.items && p.items._fal_ui_field);
function drawForm() {
  const props = SCHEMA.properties || {}, req = new Set(SCHEMA.required || []);
  const order = SCHEMA["x-fal-order-properties"] || Object.keys(props);
  const keys = order.filter(k => props[k] && fieldOk(props[k]));
  const main = keys.filter(k => req.has(k) || /^(prompt|text)$/.test(k) || fileKind(props[k]));
  const rest = keys.filter(k => !main.includes(k));
  $("#form").innerHTML = main.map(k => field(k, props[k], req.has(k))).join("") +
    (rest.length ? `<details class="more"><summary>More settings</summary><div class="form">${rest.map(k => field(k, props[k], false)).join("")}</div></details>` : "");
  $("#form").querySelectorAll("[data-k]").forEach(bind);
  updateRun();
}
function fieldOk(p) {
  if (fileKind(p)) return true;
  if (p.enum || ["string", "integer", "number", "boolean"].includes(p.type)) return true;
  return p.type === "array" && p.items && p.items.type === "string";
}
function label(k) { return k.replace(/_url(s?)$/, "$1").replace(/_/g, " ").replace(/^./, c => c.toUpperCase()); }
function field(k, p, required) {
  const hint = p.description ? `<span class="hint">${esc(p.description.slice(0, 160))}</span>` : "";
  const name = `${esc(p.title || label(k))}${required ? " *" : ""}`;
  const fk = fileKind(p);
  if (fk) return `<div class="field" data-k="${esc(k)}" data-file="${fk}" data-many="${p.type === "array" ? 1 : ""}"><label class="field">${name}${hint}</label><div class="files"><button type="button" class="add">＋ Add ${fk}</button></div><input type="file" accept="${fk}/*" ${p.type === "array" ? "multiple" : ""} hidden></div>`;
  if (p.enum) return `<label class="field">${name}${hint}<select data-k="${esc(k)}">${required ? "" : `<option value="">Default${p.default != null ? ` (${esc(p.default)})` : ""}</option>`}${p.enum.map(v => `<option ${v === p.default && required ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`;
  if (p.type === "boolean") return `<label class="toggle"><input type="checkbox" data-k="${esc(k)}" ${p.default ? "checked" : ""}> ${name}</label>`;
  if (p.type === "integer" || p.type === "number") return `<label class="field">${name}${hint}<input type="number" data-k="${esc(k)}" ${p.minimum != null ? `min="${p.minimum}"` : ""} ${p.maximum != null ? `max="${p.maximum}"` : ""} step="${p.type === "integer" ? 1 : "any"}" placeholder="${p.default != null ? esc(p.default) : ""}"></label>`;
  if (p.type === "array") return `<label class="field">${name}<span class="hint">One per line</span><textarea data-k="${esc(k)}" data-lines="1" style="min-height: 70px"></textarea></label>`;
  const big = /prompt|^text$|script|lyrics/.test(k);
  return big ? `<label class="field">${name}${hint}<textarea data-k="${esc(k)}" placeholder="${esc(p.default || "")}"></textarea></label>`
             : `<label class="field">${name}${hint}<input data-k="${esc(k)}" placeholder="${esc(p.default ?? "")}"></label>`;
}
function bind(el) {
  const k = el.dataset.k;
  if (el.dataset.file) {
    const input = el.querySelector("input[type=file]"), box = el.querySelector(".files");
    el.querySelector(".add").onclick = () => input.click();
    input.onchange = async () => { for (const f of input.files) await addFile(k, f, box, !!el.dataset.many); input.value = ""; };
    return;
  }
  const set = () => {
    let v = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "number") v = v === "" ? undefined : Number(v);
    else if (el.dataset.lines) v = v.split("\n").map(s => s.trim()).filter(Boolean);
    if (v === "" || (Array.isArray(v) && !v.length)) delete VALUES[k]; else VALUES[k] = v;
    updateRun(); quoteSoon();
  };
  el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", set);
  if (el.tagName === "TEXTAREA" && !el.dataset.lines) el.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#run").click(); });
  if (el.tagName === "SELECT" && el.value) set();
}
async function addFile(k, f, box, many) {
  const thumb = document.createElement("div"); thumb.className = "thumb";
  const url = URL.createObjectURL(f);
  thumb.innerHTML = f.type.startsWith("video") ? `<video src="${url}" muted></video>` : f.type.startsWith("image") ? `<img src="${url}" alt="">` : `<span class="muted" style="font-size: 11px; padding: 6px; display: block">${esc(f.name)}</span>`;
  box.prepend(thumb);
  try {
    const up = await api("/v1/uploads", { file_name: f.name, content_type: f.type || "application/octet-stream" });
    const r = await fetch(up.upload_url, { method: "PUT", body: f, headers: { "Content-Type": f.type || "application/octet-stream" } });
    if (!r.ok) throw new Error("The upload didn't go through. Try again.");
    if (many) (VALUES[k] ||= []).push(up.file_url); else { box.querySelectorAll(".thumb").forEach(t => t !== thumb && t.remove()); VALUES[k] = up.file_url; }
    const x = document.createElement("button"); x.type = "button"; x.textContent = "✕"; x.title = "Remove";
    x.onclick = () => { thumb.remove(); if (many) VALUES[k] = (VALUES[k] || []).filter(u => u !== up.file_url); else delete VALUES[k]; updateRun(); quoteSoon(); };
    thumb.append(x); updateRun(); quoteSoon();
  } catch (e) { thumb.remove(); toast(e.status === 402 ? "Top up your balance to upload files." : e.message); }
}
function missing() { return (SCHEMA?.required || []).filter(k => VALUES[k] == null && (SCHEMA.properties[k] || {}).default == null); }
function updateRun() {
  const m = missing();
  $("#run").disabled = !MODEL || m.length > 0;
  $("#run").title = m.length ? "Fill in: " + m.map(label).join(", ") : "";
}
// open models: the supplier the user chose for each model (blank = best price)
const pref = () => (MODEL && store.get("ml_sup:" + MODEL.id)) || "";
$("#supSel").onchange = () => { store.set("ml_sup:" + MODEL.id, $("#supSel").value || null); quoteSoon(); };
let qTimer;
function quoteSoon() {
  clearTimeout(qTimer);
  qTimer = setTimeout(async () => {
    if (!MODEL) return;
    try {
      const q = await api("/v1/quote", { model: MODEL.id, input: VALUES, provider: pref() || undefined });
      $("#price").textContent = "This run: " + money(q.price) + (q.hosted ? ` · run by ${q.provider_name}` : "");
      $("#run").textContent = "Run · " + money(q.price);
      $("#supplier").hidden = !q.choices;
      if (q.choices) $("#supSel").innerHTML = `<option value="">Best price (${money(q.choices[0].price)})</option>` +
        q.choices.map(c => `<option value="${esc(c.id)}" ${c.id === pref() ? "selected" : ""}>${esc(c.name)} · ${money(c.price)}</option>`).join("");
    } catch (e) {
      if (e.status === 409 && pref()) { store.set("ml_sup:" + MODEL.id, null); toast(e.message + " Switched to Best price.", 6000); return quoteSoon(); }
      $("#price").textContent = ""; $("#run").textContent = "Run";
    }
  }, 350);
}

// ---------- running ----------
$("#run").onclick = async () => {
  if ($("#run").disabled) return;
  $("#run").disabled = true;
  const item = { id: null, status: "submitting", model: MODEL.id, input: { ...VALUES }, created: Date.now() / 1000 };
  LATEST.unshift(item); drawLatest();
  try {
    const r = await api("/v1/runs", { model: MODEL.id, input: VALUES, provider: pref() || undefined });
    Object.assign(item, { id: r.id, status: "running", charged: r.charged });
    ME.balance -= r.charged; drawBalance(); drawLatest(); watch(item);
  } catch (e) {
    LATEST.shift(); drawLatest();
    if (e.status === 402) { toast(e.message, 6000); openTopup(); } else toast(e.message, 6000);
  } finally { updateRun(); }
};
async function watch(item) {
  while (item.status === "running" || item.status === "submitting") {
    await new Promise(r => setTimeout(r, 2500));
    try { Object.assign(item, await api("/v1/runs/" + item.id)); } catch {}
    drawLatest();
  }
  if (item.status !== "done") refreshMe();  // refunded
  HIST.unshift(item);
}

// ---------- results ----------
const ext = u => (u.split("?")[0].match(/\.(\w+)$/) || [])[1]?.toLowerCase() || "";
const isVideo = u => ["mp4", "webm", "mov", "m4v"].includes(ext(u)), isAudio = u => ["mp3", "wav", "ogg", "m4a", "flac", "aac"].includes(ext(u));
function mediaHtml(u, big) {
  if (isVideo(u)) return `<video src="${esc(u)}" ${big ? "controls autoplay loop" : "muted loop playsinline"}></video>`;
  if (isAudio(u)) return `<audio src="${esc(u)}" controls></audio>`;
  return `<img src="${esc(u)}" alt="" loading="lazy">`;
}
function tile(run) {
  const label = esc((run.input && (run.input.prompt || run.input.text)) || (MODELS.find(m => m.id === run.model)?.name) || run.model);
  if (run.status === "done" && run.outputs?.length) return `<div class="item" data-id="${esc(run.id)}">${mediaHtml(run.outputs[0])}<div class="meta"><span>${label}</span><span>${money(run.charged || 0)}</span></div></div>`;
  if (run.status === "failed" || run.status === "cancelled") return `<div class="item fail"><div class="state">${run.status === "failed" ? "This run didn't work" : "Cancelled"}. You weren't charged.<br><span class="muted">${esc((run.error || "").slice(0, 140))}</span></div></div>`;
  return `<div class="item wait"><div class="state">${run.queue_position ? `In the queue · ${run.queue_position} ahead` : "Creating…"}</div></div>`;
}
function drawLatest() {
  const items = [...LATEST, ...HIST.filter(h => !LATEST.some(l => l.id === h.id))].slice(0, 12);
  $("#latest").innerHTML = items.length ? items.map(tile).join("") : `<div class="empty">Your creations will appear here.</div>`;
}
function drawHistory() {
  $("#historyGrid").innerHTML = HIST.length ? HIST.map(tile).join("") : `<div class="empty">Nothing yet: make something on the Create tab.</div>`;
  $("#more").hidden = HIST_DONE || !HIST.length;
}
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
function openViewer(run) {
  const u = run.outputs[0];
  $("#vMedia").innerHTML = mediaHtml(u, true);
  const prompt = run.input && (run.input.prompt || run.input.text);
  $("#vSide").innerHTML = `<b style="font-size: 16px">${esc(MODELS.find(m => m.id === run.model)?.name || run.model)}</b>
    ${prompt ? `<div class="prompt">${esc(prompt)}</div>` : ""}
    <span class="muted">${new Date(run.created * 1000).toLocaleString()} · ${money(run.charged || 0)}${run.provider_name ? ` · run by ${esc(run.provider_name)}` : ""}</span>
    ${run.outputs.length > 1 ? `<span class="muted">${run.outputs.length} results</span>` : ""}
    <div class="row"><a class="btn small primary" href="${esc(u)}" target="_blank" rel="noopener" download>Download</a>
    <button class="btn small" id="vAgain">Use these settings</button><button class="btn small" id="vDelete">Delete</button><button class="btn small ghost" id="vClose">Close</button></div>`;
  $("#viewer").hidden = false;
  $("#vClose").onclick = () => { $("#viewer").hidden = true; $("#vMedia").innerHTML = ""; };
  $("#vAgain").onclick = async () => {
    $("#vClose").click(); document.querySelector('.top .tabs [data-view="create"]').click();
    await pickModel(MODELS.find(m => m.id === run.model));
    for (const [k, v] of Object.entries(run.input || {})) { const el = $(`#form [data-k="${CSS.escape(k)}"]`); if (el && el.tagName !== "DIV") { if (el.type === "checkbox") el.checked = !!v; else el.value = Array.isArray(v) ? v.join("\n") : v; el.dispatchEvent(new Event(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input")); } }
  };
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
