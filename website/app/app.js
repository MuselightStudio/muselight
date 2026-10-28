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
  READY ||= setup();
  await READY;
  loadHistory(true);
}
function drawBalance() { $("#bal").textContent = money(ME.balance); $("#bal").classList.toggle("low", ME.balance < 1); }
async function refreshMe() { try { ME = await api("/v1/me"); drawBalance(); } catch {} }
// ---------- the Create menu: every tool, grouped; each item opens a pane (and a mode of it) ----------
const GO = {
  guided: ["guided"], simple: ["create", null], apps: ["apps"], image: ["create", "image"], edit: ["edit"], batch: ["batch"], compare: ["compare"],
  video: ["create", "video"], storyboard: ["storyboard"], timeline: ["timeline"], voice: ["audio", "voice"], music: ["audio", "music"], sfx: ["audio", "sfx"],
  lipsync: ["audio", "lipsync"], clone: ["voiceclone"], sketch: ["sketch"], marketing: ["marketing"], workflows: ["workflows"], series: ["series"], influencer: ["influencer"],
};
const PANE_NAMES = { guided: "Guided", apps: "Apps", edit: "Images › Edit", batch: "Images › Variations", compare: "Images › Compare models", storyboard: "Video › Film",
  timeline: "Video › Editor", marketing: "Ads", workflows: "Pipelines", series: "Social › Story series", sketch: "Images › Sketch", voiceclone: "Audio › Voice clone", influencer: "Social › AI influencer" };
const CREATE_INTRO = { "": "Any of over a thousand models, with all its settings.", image: "Make pictures from a description, or change and restyle photos you add.", video: "Make video clips from a description, or bring a picture to life." };
const DEFAULT_MODEL = { image: ["fal-ai/nano-banana-2", "fal-ai/flux/schnell"], video: ["fal-ai/kling-video/v3/standard/text-to-video", "fal-ai/kling-video/v3/standard/image-to-video"] };
let CREATE_KIND = null;  // Images › Generate or Video › Generate narrows the model list; Simple shows every model
function go(dest) {
  const [view, mode] = GO[dest] || GO.simple;
  if (view === "create" && mode !== CREATE_KIND) {
    CREATE_KIND = mode || null; store.set("ml_kind", CREATE_KIND);
    if (C && CREATE_KIND && C.model && kind(C.model) !== CREATE_KIND)
      C.pick(byId(store.get("ml_model_" + CREATE_KIND)) || DEFAULT_MODEL[CREATE_KIND].map(byId).find(Boolean) || MODELS.find(m => kind(m) === CREATE_KIND));
  }
  if (view === "audio") audioMode(mode);
  $("#mega").hidden = true; $("#createBtn").setAttribute("aria-expanded", "false");
  show(view);
}
function createLabel(view) {
  if (view === "create") return CREATE_KIND ? (CREATE_KIND === "image" ? "Images › Generate" : "Video › Generate") : "Simple";
  if (view === "audio") return "Audio › " + $("#auMode .on").textContent;
  return PANE_NAMES[view];
}
$("#createBtn").onclick = e => { e.stopPropagation(); const open = $("#mega").hidden; $("#mega").hidden = !open; $("#createBtn").setAttribute("aria-expanded", String(open)); };
$("#mega").onclick = e => { const b = e.target.closest("[data-go]"); if (b) go(b.dataset.go); };
$("#seeAll").onclick = () => show("history");
$("#nav").addEventListener("click", e => { const b = e.target.closest("button[data-view]"); if (b && b.id !== "createBtn") show(b.dataset.view); });
document.addEventListener("click", e => { if (!e.target.closest(".createmenu")) $("#mega").hidden = true; });
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#mega").hidden = true; });
function show(view) {
  const inCreate = !["library", "history"].includes(view);
  $("#createBtn").classList.toggle("on", inCreate);
  document.querySelectorAll("#nav > button[data-view]").forEach(x => x.classList.toggle("on", x.dataset.view === view));
  if (inCreate) $("#createWhere").textContent = createLabel(view);
  const where = (inCreate ? createLabel(view) : "Library").split(" › ");  // "Images › Edit": section above, page name as the title
  $("#phCrumb").textContent = where.length > 1 ? where[0] : inCreate ? "Create" : "Your account"; $("#phTitle").textContent = where.at(-1);
  $("#cIntro").textContent = CREATE_INTRO[CREATE_KIND || ""];
  $("#work").hidden = view === "history"; $("#viewHistory").hidden = view !== "history";
  document.querySelectorAll("[data-pane]").forEach(p => p.hidden = p.dataset.pane !== view);
  store.set("ml_view", view);
  if (view === "guided") drawGuided();
  if (view === "apps") drawApps();
  if (view === "edit") drawEdit();
  if (view === "workflows") drawGraph().then(fitView);
  if (view === "voiceclone") drawClone();
  if (view === "series") drawSeries();
  if (view === "influencer") drawInfluencer();
  if (view === "history") drawHistory();
  if (view === "timeline") drawTimeline();
  if (view === "compare") drawCompare();
  if (view === "library") drawLibrary();
  if (view === "storyboard") drawStory();
  if (view === "marketing") drawMarketing();
}
$("#acctBtn").onclick = e => { e.stopPropagation(); $("#acctMenu").hidden = !$("#acctMenu").hidden; };
document.addEventListener("click", () => $("#acctMenu").hidden = true);
let READY = null;
async function setup() {
  CREATE_KIND = store.get("ml_kind") || null;
  C = modelBox($("#cBox"), { key: "ml_model", filter: m => !CREATE_KIND || kind(m) === CREATE_KIND,
    change: b => { if (b.model && CREATE_KIND) store.set("ml_model_" + CREATE_KIND, b.model.id); updateRun(); quoteSoon(); } });
  C.pick(byId(store.get("ml_model")) || MODELS.find(m => /flux.*schnell/.test(m.id)) || MODELS[0]);
  B = modelBox($("#bBox"), { key: "ml_bmodel", change: batchSoon });
  B.pick(byId(store.get("ml_bmodel")) || byId(store.get("ml_model")) || MODELS[0]);
  await loadAccount();
  drawWfList(); audioMode(AU_MODE);
  const v = store.get("ml_view");
  show(v && (document.querySelector(`[data-pane="${v}"]`) || ["library", "history"].includes(v)) ? v : "guided");
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
  box.redraw = () => { form.dataset.model = box.model.id; buildForm(form, box.schema, box.values, changed, o.chain); promptTools(form); changed(); };
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
  const hint = p.description ? `<span class="hint" title="${esc(p.description)}">${esc(p.description.slice(0, 160))}</span>` : "";
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
// a required file box counts as filled when the prompt mentions a Library element with that kind of file: it's added at run time
const mentionedFiles = values => Object.values(values).filter(v => typeof v === "string" && v.includes("@")).flatMap(v => [...v.matchAll(MENTION)]).map(m => libItem(m[2])).filter(Boolean).flatMap(li => li.files || []);
const missing = (schema, values) => {
  const has = new Set(mentionedFiles(values).map(mediaOf));
  return (schema.required || []).filter(k => values[k] == null && (schema.properties[k] || {}).default == null && !has.has(fileKind(schema.properties[k] || {}, k)));
};
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
// runs whose length is only known afterwards (a talking video, lip sync, a join) are charged the most they can cost; once the
// provider's bill is in, the difference comes back to the balance
const UPTO = "Charged at the most it can cost; you get the difference back a minute or two after it's done, once its real length is known.";
const cost = q => (q.upto ? "up to " : "") + money(q.price);
// starts a run, shows it under Latest, and resolves when it's finished (done, failed or cancelled)
async function launch(model, input, note) {
  const sent = await prepare(model, input);  // the brief, prompt rules and @Library names, written into what the model gets
  const item = { id: null, status: "submitting", model, input: { ...input }, note, created: Date.now() / 1000 };
  LATEST.unshift(item); drawLatest();
  try {
    const r = await api("/v1/runs", { model, input: sent, provider: pref(model) || undefined });
    Object.assign(item, { id: r.id, status: "running", charged: r.charged, upto: r.upto });
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
  else if (item.upto) setTimeout(async () => { refreshMe(); try { Object.assign(item, await api("/v1/runs/" + item.id)); drawLatest(); } catch {} }, 150000);  // settled by then
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
      $("#price").textContent = "This run: " + cost(q) + (q.hosted ? ` · run by ${q.provider_name}` : "");
      $("#price").title = q.upto ? UPTO : "";
      $("#run").textContent = "Run · " + cost(q);
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
  addModelNode(C.model.id, JSON.parse(JSON.stringify(C.values)));
  toast("Added as a node in Pipelines.");
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

// ---------- Pipelines: a node editor ----------
// Model nodes run a model; input nodes hold a prompt, a list of prompts (one run each), pictures or videos.
// A wire is a {{id}} placeholder in a model node's setting, filled in from the other node when the pipeline runs.
const WIRE = /\{\{(\w+?)(_all)?\}\}/g;
const IN_TYPES = {
  prompt: { label: "Prompt", hint: "Wire it into any text box" },
  negative: { label: "Negative prompt", hint: "What to keep out of the result" },
  batch: { label: "Prompt list", hint: "One run per prompt; put a line with only --- between prompts" },
  images: { label: "Pictures", media: "image", hint: "Your photos, used in order" },
  videos: { label: "Videos", media: "video", hint: "Your clips, used in order" },
};
// old pipelines were a list of steps fed by {{prev}}; they open as nodes in a row, each wired to the one before
function toGraph(saved) {
  if (!Array.isArray(saved)) return { nodes: saved?.nodes || [], inputs: saved?.inputs || [] };
  const nodes = saved.filter(s => s.model).map((s, i) => ({ id: "n" + (i + 1), model: s.model, values: s.values || {}, x: 380 + i * 400, y: 40 }));
  nodes.forEach((n, i) => { if (i) n.values = JSON.parse(JSON.stringify(n.values).replace(/\{\{prev(_all)?\}\}/g, (m, a) => `{{n${i}${a || ""}}}`)); });
  return { nodes, inputs: [] };
}
let WF = JSON.parse(store.get("ml_wf") || "{}");
WF = { name: WF.name || "", ...toGraph(WF.steps || WF) };
const saveWf = () => store.set("ml_wf", JSON.stringify(WF));
const NE = { pan: { x: 40, y: 30 }, z: 1, drag: null, items: {}, state: {} };
const nodeOf = id => WF.nodes.find(n => n.id === id), inputOf = id => WF.inputs.find(v => v.id === id);
const newId = p => { const used = new Set([...WF.nodes, ...WF.inputs].map(n => n.id)); let i = 1; while (used.has(p + i)) i++; return p + i; };
const prompts = t => String(t || "").split(/^\s*---\s*$/m).map(s => s.trim()).filter(Boolean);
function refsOf(n) {
  const out = [];
  for (const [k, v] of Object.entries(n.values)) for (const s of [].concat(v)) if (typeof s === "string")
    for (const m of s.matchAll(WIRE)) if ((inputOf(m[1]) || nodeOf(m[1])) && m[1] !== n.id) out.push({ field: k, from: m[1], all: !!m[2] });
  return out;
}
// model nodes in an order where every node comes after the ones it uses
function graphOrder() {
  const order = [], state = {};
  const visit = n => {
    if (state[n.id] === 2) return;
    if (state[n.id] === 1) throw new Error("The wires go round in a loop. Remove one of them.");
    state[n.id] = 1; refsOf(n).map(r => nodeOf(r.from)).filter(Boolean).forEach(visit); state[n.id] = 2; order.push(n);
  };
  WF.nodes.forEach(visit); return order;
}
const wired = id => WF.nodes.some(n => refsOf(n).some(r => r.from === id));
const runCount = () => Math.max(1, ...WF.inputs.filter(v => v.type === "batch" && wired(v.id)).map(v => prompts(v.value).length));
const inputValue = (v, run) => v.type === "batch" ? prompts(v.value)[run % Math.max(1, prompts(v.value).length)] || "" : v.value;

// the setting an input lands in when it's dropped on a node rather than on a setting's port
function autoField(from, n, schema) {
  const v = inputOf(from), props = schema.properties || {};
  if (!v) return fileKey(schema, kind(byId(nodeOf(from).model) || {}) || "image") || fileKey(schema, "image");
  if (v.type === "negative") return Object.keys(props).find(k => /negative/.test(k));
  if (IN_TYPES[v.type].media) return fileKey(schema, IN_TYPES[v.type].media);
  return promptKey(schema);
}
function connect(from, all, n, k, schema) {
  const ref = `{{${from}${all ? "_all" : ""}}}`, p = schema.properties[k] || {};
  if (fileKind(p, k) && p.type === "array") n.values[k] = [...[].concat(n.values[k] || []).filter(x => /^\{\{\w+\}\}$/.test(String(x).trim())), ref].filter((x, i, a) => a.indexOf(x) === i);
  else n.values[k] = ref;
}
function unplug(n, k, only) {  // takes the wires out of one setting (or only the one from `only`)
  const isRef = s => { const m = typeof s === "string" && s.trim().match(/^\{\{(\w+?)(_all)?\}\}$/); return !!m && (only ? m[1] === only : !!(inputOf(m[1]) || nodeOf(m[1]))); };
  const v = n.values[k];
  if (Array.isArray(v)) { const keep = v.filter(s => !isRef(s)); keep.length ? n.values[k] = keep : delete n.values[k]; }
  else if (isRef(v)) delete n.values[k];
}
const sourceName = id => { const v = inputOf(id); return v ? IN_TYPES[v.type].label : byId(nodeOf(id)?.model)?.name || id; };

const view = () => { $("#neWorld").style.transform = `translate(${NE.pan.x}px, ${NE.pan.y}px) scale(${NE.z})`; $("#neZoom").textContent = Math.round(NE.z * 100) + "%"; };
async function drawGraph() {
  view();
  const world = $("#neWorld"); world.querySelectorAll(".node").forEach(n => n.remove());
  $("#neEmpty").hidden = WF.nodes.length + WF.inputs.length > 0;
  await Promise.all(WF.nodes.map(n => schemaOf(n.model).catch(() => null)));
  for (const n of WF.nodes) world.append(await modelNode(n));
  for (const v of WF.inputs) world.append(inputNode(v));
  $("#wfName").value = WF.name || "";
  wires(); wfSoon();
}
async function modelNode(n) {
  const m = byId(n.model), el = document.createElement("div");
  el.className = "node " + (NE.state[n.id] || ""); el.dataset.id = n.id; el.style.left = n.x + "px"; el.style.top = n.y + "px";
  el.innerHTML = `<div class="nhead">${m?.thumb ? `<img src="${esc(m.thumb)}" alt="">` : ""}<div class="ntitle"><b>${esc(m?.name || n.model)}</b><span>${esc(n.id)} · ${esc(m?.cat || "model")}</span></div>
      <button class="nbtn" data-a="model" title="Change the model">⇄</button><button class="nbtn" data-a="del" title="Remove this node">✕</button></div>
    <div class="nbody"><div class="form"></div></div>
    <div class="nout"><span class="nstat"></span><span class="oport" data-out="${esc(n.id)}" title="Drag onto another node: the first result">Result</span><span class="oport" data-out="${esc(n.id)}" data-all="1" title="Drag onto another node: every result">All</span></div>
    <div class="nthumbs"></div>`;
  el.querySelector('[data-a="del"]').onclick = () => {
    WF.nodes = WF.nodes.filter(x => x !== n); WF.nodes.forEach(x => Object.keys(x.values).forEach(k => unplug(x, k, n.id)));
    saveWf(); drawGraph();
  };
  el.querySelector('[data-a="model"]').onclick = e => e.stopPropagation() || openDrop($("#nePick"), null, mm => { n.model = mm.id; n.values = {}; WF.nodes.forEach(x => Object.keys(x.values).forEach(k => unplug(x, k, n.id))); saveWf(); drawGraph(); });
  let schema; try { schema = await schemaOf(n.model); } catch (e) { el.querySelector(".form").innerHTML = `<p class="err">${esc(e.message)}</p>`; return el; }
  const form = el.querySelector(".form"), refs = refsOf(n);
  form.dataset.model = n.model;
  buildForm(form, schema, n.values, () => { saveWf(); wfSoon(); }); promptTools(form);
  form.querySelectorAll("[data-k]").forEach(c => {
    const k = c.dataset.k, wrap = c.dataset.file ? c : c.closest("label.field, label.toggle") || c;
    wrap.classList.add("nfield");
    wrap.insertAdjacentHTML("afterbegin", `<span class="iport" data-in="${esc(n.id)}" data-field="${esc(k)}" title="Drop a wire here. Click to unplug."></span>`);
    const from = refs.filter(r => r.field === k);
    if (!from.length) return;
    wrap.classList.add("wired");
    wrap.querySelectorAll("input:not([type=checkbox]), select, textarea, .files, .ptools, .pcoach").forEach(x => x.hidden = true);
    wrap.insertAdjacentHTML("beforeend", `<div class="locked">← ${from.map(r => esc(sourceName(r.from)) + (r.all ? " (all)" : "")).join(", ")}</div>`);
    const more = wrap.closest("details"); if (more) more.open = true;
  });
  thumbs(el, n.id);
  return el;
}
function inputNode(v) {
  const t = IN_TYPES[v.type], el = document.createElement("div");
  el.className = "node inode"; el.dataset.id = v.id; el.style.left = v.x + "px"; el.style.top = v.y + "px";
  el.innerHTML = `<div class="nhead"><div class="ntitle"><b>${esc(t.label)}</b><span>${esc(v.id)} · ${esc(t.hint)}</span></div><button class="nbtn" data-a="del" title="Remove this node">✕</button></div>
    <div class="nbody"></div><div class="nout"><span class="nstat"></span><span class="oport" data-out="${esc(v.id)}" title="Drag onto a model node">Output</span></div>`;
  el.querySelector('[data-a="del"]').onclick = () => {
    WF.inputs = WF.inputs.filter(x => x !== v); WF.nodes.forEach(x => Object.keys(x.values).forEach(k => unplug(x, k, v.id)));
    saveWf(); drawGraph();
  };
  const body = el.querySelector(".nbody"), stat = el.querySelector(".nstat");
  if (t.media) {
    const draw = () => {
      body.innerHTML = `<div class="files">${(v.value || []).map(thumbHtml).join("")}<button type="button" class="add">＋ Add ${t.media}s</button></div><input type="file" accept="${t.media}/*" multiple hidden>`;
      const fi = body.querySelector("input");
      body.querySelector(".add").onclick = () => fi.click();
      body.querySelectorAll(".thumb button").forEach(b => b.onclick = () => { v.value = v.value.filter(u => u !== b.parentNode.dataset.u); saveWf(); draw(); wfSoon(); });
      fi.onchange = async () => {
        for (const f of fi.files) try { (v.value ||= []).push(await upload(f)); } catch (e) { toast(e.message); }
        saveWf(); draw(); wfSoon();
      };
    };
    draw();
  } else {
    body.innerHTML = `<textarea placeholder="${v.type === "batch" ? "A cat in a spacesuit\n---\nA dog in a spacesuit" : t.label + "…"}"></textarea>`;
    const ta = body.querySelector("textarea"); ta.value = v.value || "";
    const count = () => { if (v.type === "batch") { const c = prompts(ta.value).length; stat.textContent = `${c} prompt${c === 1 ? "" : "s"} → ${c} run${c === 1 ? "" : "s"}`; } };
    ta.oninput = () => { v.value = ta.value; saveWf(); count(); wfSoon(); }; count();
    if (v.type !== "negative") promptHelp(ta, () => byId(WF.nodes.find(n => refsOf(n).some(r => r.from === v.id))?.model));
  }
  return el;
}
function thumbs(el, id) {
  const item = NE.items[id], box = el.querySelector(".nthumbs"), st = NE.state[id];
  el.classList.remove("running", "done", "error"); if (st) el.classList.add(st);
  el.querySelector(".nstat").textContent = st === "running" ? "Running…" : st === "error" ? "Didn't work" : st === "done" ? "Done" : "";
  box.innerHTML = item?.outputs?.length ? item.outputs.slice(0, 6).map((u, i) => mediaOf(u) === "audio" ? `<button data-i="${i}" class="aud">♪</button>` : `<button data-i="${i}">${isVideo(u) ? `<video src="${esc(u)}#t=0.1" muted preload="metadata"></video>` : `<img src="${esc(u)}" alt="">`}</button>`).join("") : "";
  box.querySelectorAll("button").forEach(b => b.onclick = () => openViewer(item, +b.dataset.i));
}

// wires: from an output to the round port beside a setting
function spot(el) {
  const r = el.getBoundingClientRect(), c = $("#neCanvas").getBoundingClientRect();
  return { x: (r.left + r.width / 2 - c.left - NE.pan.x) / NE.z, y: (r.top + r.height / 2 - c.top - NE.pan.y) / NE.z };
}
const curve = (a, b) => { const dx = Math.max(60, Math.abs(b.x - a.x) / 2); return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`; };
function wires(temp) {
  let h = "";
  for (const n of WF.nodes) for (const r of refsOf(n)) {
    const o = document.querySelector(`.node[data-id="${r.from}"] .oport${r.all ? "[data-all]" : ":not([data-all])"}`);
    const i = document.querySelector(`.node[data-id="${n.id}"] .iport[data-field="${r.field}"]`);
    if (o && i) h += `<path class="wire" d="${curve(spot(o), spot(i))}"/>`;
  }
  if (temp) h += `<path class="wire temp" d="${curve(temp.a, temp.b)}"/>`;
  $("#neWires").innerHTML = h;
}
const toWorld = e => { const c = $("#neCanvas").getBoundingClientRect(); return { x: (e.clientX - c.left - NE.pan.x) / NE.z, y: (e.clientY - c.top - NE.pan.y) / NE.z }; };
$("#neCanvas").onpointerdown = e => {
  const t = e.target;
  if (!t.closest(".node") && t.closest("button")) return;
  if (t.classList.contains("iport")) { const n = nodeOf(t.dataset.in); unplug(n, t.dataset.field); saveWf(); drawGraph(); return; }
  if (t.classList.contains("oport")) NE.drag = { type: "wire", from: t.dataset.out, all: !!t.dataset.all, a: spot(t) };
  else if (t.closest(".nhead") && !t.closest("button")) {
    const el = t.closest(".node"), n = nodeOf(el.dataset.id) || inputOf(el.dataset.id);
    NE.drag = { type: "node", n, el, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y };
  } else if (!t.closest(".node")) NE.drag = { type: "pan", sx: e.clientX, sy: e.clientY, ox: NE.pan.x, oy: NE.pan.y };
  else return;
  e.preventDefault(); $("#neCanvas").setPointerCapture(e.pointerId); $("#neCanvas").classList.add("dragging");
};
$("#neCanvas").onpointermove = e => {
  const d = NE.drag; if (!d) return;
  if (d.type === "node") { d.n.x = Math.round(d.ox + (e.clientX - d.sx) / NE.z); d.n.y = Math.round(d.oy + (e.clientY - d.sy) / NE.z); d.el.style.left = d.n.x + "px"; d.el.style.top = d.n.y + "px"; wires(); }
  if (d.type === "pan") { NE.pan = { x: d.ox + e.clientX - d.sx, y: d.oy + e.clientY - d.sy }; view(); }
  if (d.type === "wire") wires({ a: d.a, b: toWorld(e) });
};
$("#neCanvas").onpointerup = async e => {
  const d = NE.drag; NE.drag = null; $("#neCanvas").classList.remove("dragging"); if (!d) return;
  if (d.type === "node") saveWf();
  if (d.type !== "wire") return wires();
  const t = document.elementFromPoint(e.clientX, e.clientY), target = t?.closest(".node:not(.inode)");
  if (!target || target.dataset.id === d.from) return wires();
  const n = nodeOf(target.dataset.id), schema = await schemaOf(n.model);
  const k = t.classList.contains("iport") ? t.dataset.field : autoField(d.from, n, schema);
  if (!k) { toast("This model has no setting that fits. Drop the wire on the round port beside the setting you want."); return wires(); }
  const before = JSON.stringify(n.values);
  connect(d.from, d.all, n, k, schema);
  try { graphOrder(); } catch (err) { n.values = JSON.parse(before); toast(err.message); }
  saveWf(); drawGraph();
};
// the mouse wheel scrolls the page as usual; Ctrl + wheel (or a trackpad pinch) zooms
$("#neCanvas").addEventListener("wheel", e => {
  if (!e.ctrlKey && !e.metaKey) return;
  e.preventDefault(); zoomAt(NE.z * (e.deltaY < 0 ? 1.1 : 0.9), e);
}, { passive: false });
function zoomAt(z, e) {
  const c = $("#neCanvas").getBoundingClientRect(), at = e || { clientX: c.left + c.width / 2, clientY: c.top + c.height / 2 }, before = toWorld(at);
  NE.z = Math.min(1.5, Math.max(0.3, z));
  NE.pan = { x: at.clientX - c.left - before.x * NE.z, y: at.clientY - c.top - before.y * NE.z }; view(); wires();
}
$("#neIn").onclick = () => zoomAt(NE.z * 1.2);
$("#neOut").onclick = () => zoomAt(NE.z / 1.2);
function fitView() {
  const els = [...document.querySelectorAll("#neWorld .node")]; if (!els.length) return;
  const xs = [...WF.nodes, ...WF.inputs].map(n => n.x), ys = [...WF.nodes, ...WF.inputs].map(n => n.y), c = $("#neCanvas").getBoundingClientRect();
  const w = Math.max(...els.map(el => el.offsetLeft + el.offsetWidth)) - Math.min(...xs), h = Math.max(...els.map(el => el.offsetTop + el.offsetHeight)) - Math.min(...ys);
  NE.z = Math.min(1, Math.max(0.3, Math.min((c.width - 60) / w, (c.height - 60) / h)));
  NE.pan = { x: (c.width - w * NE.z) / 2 - Math.min(...xs) * NE.z, y: (c.height - h * NE.z) / 2 - Math.min(...ys) * NE.z }; view(); wires();
}
$("#neFit").onclick = fitView;
document.addEventListener("keydown", e => { if (e.key === "Escape" && $("#wfPanel").classList.contains("full")) $("#neFull").click(); });
$("#neFull").onclick = () => { const on = $("#wfPanel").classList.toggle("full"); $("#neFull").textContent = on ? "Exit full screen" : "Full screen"; document.body.style.overflow = on ? "hidden" : ""; setTimeout(fitView); };
// new model nodes go to the right of the others, inputs to the left, so nothing lands on top of another node
const freeSpot = left => {
  const all = [...WF.nodes, ...WF.inputs]; if (!all.length) return { x: left ? 0 : 400, y: 0 };
  return { x: left ? Math.min(...all.map(n => n.x)) - 400 : Math.max(...all.map(n => n.x)) + 400, y: Math.min(...all.map(n => n.y)) };
};
function addModelNode(id, values = {}) {
  WF.nodes.push({ id: newId("n"), model: id, values, ...freeSpot(false) }); saveWf(); drawGraph().then(fitView);
}
$("#neAdd").onclick = () => openDrop($("#nePick"), null, m => addModelNode(m.id));
$("#neAddIn").onchange = () => {
  const type = $("#neAddIn").value; $("#neAddIn").value = ""; if (!IN_TYPES[type]) return;
  WF.inputs.push({ id: newId(type === "images" || type === "videos" ? "m" : "p"), type, value: IN_TYPES[type].media ? [] : "", ...freeSpot(true) }); saveWf(); drawGraph().then(fitView);
};

// price, and what's missing before it can run
let wfTimer;
function wfSoon() {
  clearTimeout(wfTimer);
  wfTimer = setTimeout(async () => {
    $("#wfRun").disabled = true; $("#wfPrice").textContent = "";
    if (!WF.nodes.length) return;
    try { graphOrder(); } catch (e) { $("#wfPrice").textContent = e.message; return; }
    const schemas = await Promise.all(WF.nodes.map(n => schemaOf(n.model).catch(() => null)));
    const gap = WF.nodes.map((n, i) => schemas[i] && missing(schemas[i], n.values).length ? `${byId(n.model)?.name || n.model} needs ${missing(schemas[i], n.values).map(label).join(", ")}` : "").find(Boolean);
    const empty = WF.inputs.find(v => wired(v.id) && !(v.type === "batch" ? prompts(v.value).length : v.value?.length));
    if (gap || empty) { $("#wfPrice").textContent = gap || `Fill in the ${IN_TYPES[empty.type].label.toLowerCase()} node`; return; }
    $("#wfRun").disabled = false;
    try {  // results from earlier nodes are priced with a stand-in picture; the exact price is charged as each node starts
      const sample = "https://v3.fal.media/files/sample/sample.png", vars = {};
      WF.nodes.forEach(n => { vars[n.id] = sample; vars[n.id + "_all"] = [sample]; });
      WF.inputs.forEach(v => vars[v.id] = inputValue(v, 0) || (IN_TYPES[v.type].media ? [sample] : "a sample prompt"));
      const qs = await Promise.all(WF.nodes.map((n, i) => quote(n.model, fitInput(fillVars(n.values, vars), schemas[i]))));
      const runs = runCount(), total = qs.reduce((a, q) => a + q.price, 0) * runs;
      $("#wfPrice").textContent = `${WF.nodes.length} ${WF.nodes.length === 1 ? "node" : "nodes"}${runs > 1 ? ` × ${runs} runs` : ""} · about ${money(total)}`;
      $("#wfRun").textContent = runs > 1 ? `Run ${runs} times` : "Run pipeline";
    } catch { $("#wfPrice").textContent = "Each node is priced when it starts"; }
  }, 400);
}
// a setting that takes one file gets the first of a list; one that takes several gets them all
const fitInput = (input, schema) => Object.fromEntries(Object.entries(input).map(([k, v]) => [k, Array.isArray(v) && schema?.properties?.[k] && schema.properties[k].type !== "array" ? v[0] : v]));
$("#wfRun").onclick = async () => {
  $("#wfRun").disabled = true;
  const order = graphOrder(), runs = runCount(), name = WF.name || "Pipeline";
  NE.state = {}; NE.items = {};
  const once = async run => {
    const vars = {}, started = {};
    WF.inputs.forEach(v => vars[v.id] = inputValue(v, run));
    const go = n => started[n.id] ||= (async () => {
      await Promise.all(refsOf(n).map(r => nodeOf(r.from)).filter(Boolean).map(go));
      NE.state[n.id] = "running"; redrawNode(n.id);
      const item = await launch(n.model, fitInput(fillVars(n.values, vars), await schemaOf(n.model)), `${name}${runs > 1 ? ` · run ${run + 1}` : ""} · ${byId(n.model)?.name || n.id}`);
      NE.items[n.id] = NE.items[n.id]?.outputs ? { ...item, outputs: [...NE.items[n.id].outputs, ...(item.outputs || [])] } : item;  // every run's results
      if (item.status !== "done" || !item.outputs?.length) { NE.state[n.id] = "error"; redrawNode(n.id); throw new Error(`${byId(n.model)?.name || n.id} didn't work${item.error ? ": " + item.error : ""}. You weren't charged for it.`); }
      NE.state[n.id] = "done"; redrawNode(n.id);
      vars[n.id] = item.outputs[0]; vars[n.id + "_all"] = item.outputs;
    })();
    return Promise.all(order.map(go));
  };
  const out = await Promise.allSettled(Array.from({ length: runs }, (_, i) => once(i)));
  const failed = out.find(r => r.status === "rejected");
  toast(failed ? failed.reason.message : runs > 1 ? `All ${runs} runs finished.` : "Pipeline finished.", failed ? 8000 : 4000);
  wfSoon();
};
const redrawNode = id => { const el = document.querySelector(`#neWorld .node[data-id="${id}"]`); if (el) thumbs(el, id); };

// saved pipelines, kept in the account
function drawWfList() {
  const names = Object.keys(ACC.workflows).sort();
  $("#wfList").innerHTML = `<option value="">${names.length ? "Open a saved pipeline…" : "No saved pipelines yet"}</option>` + names.map(n => `<option>${esc(n)}</option>`).join("");
}
$("#wfList").onchange = () => {
  const name = $("#wfList").value; if (!name) return;
  if (WF.nodes.length && !confirm(`Replace what's on the canvas with “${name}”?`)) { $("#wfList").value = ""; return; }
  WF = { name, ...toGraph(JSON.parse(JSON.stringify(ACC.workflows[name]))) }; NE.state = {}; NE.items = {};
  saveWf(); drawGraph().then(fitView);
};
$("#wfSave").onclick = () => {
  const name = $("#wfName").value.trim(); if (!name) return toast("Give the pipeline a name.");
  if (!WF.nodes.length) return toast("Add a model node first.");
  if (ACC.workflows[name] && !Array.isArray(ACC.workflows[name]) && WF.name !== name && !confirm(`Replace the saved pipeline “${name}”?`)) return;
  WF.name = name; ACC.workflows[name] = JSON.parse(JSON.stringify({ nodes: WF.nodes, inputs: WF.inputs }));
  keep("workflows"); saveWf(); drawWfList(); toast(`Saved “${name}”.`);
};
$("#wfDel").onclick = () => {
  const name = WF.name; if (!name || !ACC.workflows[name]) return toast("Open a saved pipeline to delete it.");
  if (!confirm(`Delete the saved pipeline “${name}”?`)) return;
  delete ACC.workflows[name]; keep("workflows"); drawWfList();
};
$("#wfNew").onclick = () => { if (WF.nodes.length && !confirm("Clear the canvas?")) return; WF = { name: "", nodes: [], inputs: [] }; NE.state = {}; NE.items = {}; saveWf(); drawGraph(); };
$("#wfName").oninput = () => { WF.name = $("#wfName").value; saveWf(); };
$("#neStart").onclick = async () => {  // a starter: a prompt into a picture model, its picture into a video model
  const pic = DEFAULT_MODEL.image.find(byId), vid = DEFAULT_MODEL.video.slice(1).find(byId);
  if (!pic || !vid) return toast("The starter models aren't available right now. Add nodes with ＋ Model.");
  WF = { name: WF.name, inputs: [{ id: "p1", type: "prompt", value: "", x: 0, y: 40 }], nodes: [{ id: "n1", model: pic, values: {}, x: 400, y: 0 }, { id: "n2", model: vid, values: {}, x: 800, y: 0 }] };
  const [ps, vs] = await Promise.all([schemaOf(pic), schemaOf(vid)]);
  connect("p1", false, WF.nodes[0], promptKey(ps), ps); connect("n1", false, WF.nodes[1], fileKey(vs, "image"), vs);
  saveWf(); drawGraph().then(fitView);
};

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
  const voiced = AU_MODE === "voice" ? ACC.library.filter(li => li.kind === "character" && li.voice) : [];
  $("#auChar").hidden = !voiced.length;
  $("#auChar").innerHTML = `<option value="">Speak as a Library character…</option>` + voiced.map(li => `<option>${esc(li.name)}</option>`).join("");
  AU = modelBox($("#auBox"), { key: "ml_au_" + AU_MODE, filter: M.test, change: auSoon });
  AU.ready = AU.pick(byId(store.get("ml_au_" + AU_MODE)) || M.prefer.map(byId).find(Boolean) || MODELS.find(M.test));
}
$("#auChar").onchange = e => { const li = ACC.library.find(x => x.name === e.target.value); if (li && AU.schema?.properties?.voice) { AU.values.voice = li.voice; AU.redraw(); } };
$("#auMode").onclick = e => { const b = e.target.closest("button"); if (b) audioMode(b.dataset.m); };
let auTimer;
function auSoon() {
  clearTimeout(auTimer);
  auTimer = setTimeout(async () => {
    const m = AU.missing(); $("#auRun").disabled = m.length > 0; $("#auPrice").textContent = m.length && AU.schema ? "Fill in: " + m.map(label).join(", ") : "";
    if (m.length) return;
    try { const q = await quote(AU.model.id, AU.values); $("#auPrice").textContent = "This run: " + cost(q); $("#auPrice").title = q.upto ? UPTO : ""; } catch {}
  }, 350);
}
$("#auRun").onclick = async () => { $("#auRun").disabled = true; launch(AU.model.id, AU.values, $("#auMode .on").textContent).catch(e => toast(e.message, 6000)).finally(auSoon); };

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

// ---------- kept in the account: the Library, saved workflows and prompt settings ----------
const ACC = { library: [], workflows: {}, settings: { brief: "", brief_on: false, rules: { realism: true, capture: true, ugc: true } } };
const accTimers = {};
function keep(name) {
  clearTimeout(accTimers[name]);
  accTimers[name] = setTimeout(() => api("/v1/store/" + name, { value: ACC[name] }).catch(e => toast("Couldn't save to your account: " + e.message, 6000)), 500);
}
async function loadAccount() {
  await Promise.all(Object.keys(ACC).map(async name => {
    try { const v = (await api("/v1/store/" + name)).value; if (v != null) ACC[name] = name === "settings" ? { ...ACC.settings, ...v } : v; } catch {}
  }));
  const local = JSON.parse(store.get("ml_workflows") || "{}");  // saved in this browser before workflows moved into the account
  if (Object.keys(local).length) { ACC.workflows = { ...local, ...ACC.workflows }; keep("workflows"); store.set("ml_workflows", null); }
}

// ---------- Library: characters, products, places, styles and brand kits, reused with @name ----------
const LIB_KINDS = { character: "Character", product: "Product", location: "Location", style: "Style", brand: "Brand kit" };
const libTag = name => String(name).replace(/[^\w-]+/g, "-").replace(/^-+|-+$/g, "");
const libItem = token => ACC.library.find(li => li.name && libTag(li.name).toLowerCase() === token.toLowerCase());
// a brand kit's colours, fonts and voice become its description, so @Brand carries them (and its logo) into any prompt
const brandNotes = b => [b.colours?.length && `brand colours ${b.colours.join(", ")}`, b.fonts && `typography in the style of ${b.fonts}`, b.tone && `tone: ${b.tone}`, b.rules].filter(Boolean).join("; ");
// Written for Muselight. Each is added only when the prompt uses its words, so stylised work is left alone (same as the Windows app).
const REAL = /\b(photo-?real\w*|realis(m|tic)|hyper-?real\w*|ultra-?real\w*|lifelike|true[- ]to[- ]life|skin (texture|detail)|natural skin|pores|unretouched|candid photo|raw photo)\b/i;
const RULES = {
  realism: { label: "Real skin and hair", hint: "when the prompt says realistic, photoreal, skin texture…", when: t => REAL.test(t),
    text: "Skin should look photographed, not retouched: visible pores, fine lines, small blemishes and natural colour variation (warmer nose and cheeks, cooler under the eyes), a slight natural sheen on the forehead and nose, and normal facial asymmetry. Eyes are moist with a real catchlight and individual lashes. Hair falls as separate strands with flyaways and baby hairs, some crossing the face and casting small shadows. No airbrushing, plastic or waxy skin, or beauty filter." },
  capture: { label: "Looks like a real camera", hint: "same words: grain, natural focus, no CGI sheen", when: t => REAL.test(t),
    text: "It should read as a photo a real camera took: fine grain, focus that falls off naturally away from the subject, highlights allowed to clip, no digital over-sharpening, HDR look, glow around the subject or glossy CGI finish. Keep the framing, lens and lighting asked for above." },
  ugc: { label: "Natural UGC acting", hint: "when the prompt says UGC, talking head, selfie video…", when: t => /\b(ugc|user[- ]generated|talking head|selfie video|vlog|testimonial)\b/i.test(t),
    text: "Film it like a real person recording themselves on a phone: the camera is hand-held or propped, so the framing drifts a little. They blink naturally and irregularly, glance away and back to the lens, start mid-thought, and include one small unplanned moment (touching their hair, a breath, a tiny stumble). Casual, believable, not a polished presenter." },
};
function drawLibrary() {
  $("#brief").value = ACC.settings.brief || ""; $("#briefOn").checked = !!ACC.settings.brief_on;
  $("#libRules").innerHTML = Object.entries(RULES).map(([k, r]) => `<label class="toggle"><input type="checkbox" data-rule="${k}" ${ACC.settings.rules?.[k] ? "checked" : ""}> ${esc(r.label)} <span class="muted small">${esc(r.hint)}</span></label>`).join("");
  const list = $("#libList"); list.innerHTML = ACC.library.length ? "" : `<p class="muted">Nothing saved yet. Add your main character or product first.</p>`;
  ACC.library.forEach((li, i) => {
    const d = document.createElement("div"); d.className = "libcard";
    const b = li.brand || {};
    d.innerHTML = `<div class="libhead"><input data-f="name" value="${esc(li.name)}" placeholder="Name, e.g. Mia"><select data-f="kind">${Object.entries(LIB_KINDS).map(([k, v]) => `<option value="${k}"${li.kind === k ? " selected" : ""}>${v}</option>`).join("")}</select><code>@${esc(libTag(li.name) || "name")}</code><button class="btn small ghost" data-a="del" title="Remove">✕</button></div>
      <div class="files">${(li.files || []).map(thumbHtml).join("")}<button type="button" class="add">＋ ${li.kind === "brand" ? "Add the logo" : "Add reference images"}</button></div><input type="file" accept="image/*" multiple hidden>
      ${li.kind === "brand" ? `<div class="row swatches">${(b.colours || []).map((c, k) => `<input type="color" value="${esc(c)}" data-c="${k}">`).join("")}<button class="btn small ghost" data-a="addc">＋ Colour</button></div>
        <div class="row"><input data-b="fonts" value="${esc(b.fonts || "")}" placeholder="Fonts, e.g. bold geometric sans like Futura"><input data-b="tone" value="${esc(b.tone || "")}" placeholder="Tone, e.g. confident, warm, minimal"></div>
        <input data-b="rules" value="${esc(b.rules || "")}" placeholder="Always or never, e.g. lots of white space, no competitors' logos">`
      : `<textarea data-f="notes" placeholder="Description sent with it the first time it's mentioned, e.g. “25-year-old woman, freckles, short red hair, green bomber jacket”">${esc(li.notes || "")}</textarea>`}
      ${li.kind === "character" ? `<label class="field">Voice<span class="hint">An ElevenLabs voice name, used by Audio → Voice</span><input data-f="voice" value="${esc(li.voice || "")}" placeholder="e.g. Rachel"></label>
        <div class="row"><button class="btn small" data-a="set" title="15 different scenes of this character, same face (Batch tab)">Photo set</button>
        <button class="btn small" data-a="train" title="Train a personal identity model from this character's photos. Best with 10-20 varied, clear photos.">${li.lora ? "Retrain identity" : "Train identity"}</button>
        ${li.lora ? `<button class="btn small" data-a="useid">Use trained identity</button>` : ""}<span class="muted small idstat">${li.trainRun && !li.lora ? "Training identity… (5-10 min)" : ""}</span></div>` : ""}`;
    const save = () => keep("library");
    d.querySelectorAll("[data-f]").forEach(x => x.onchange = () => {
      li[x.dataset.f] = x.value.trim(); save();
      if (x.dataset.f === "kind") drawLibrary(); else if (x.dataset.f === "name") d.querySelector("code").textContent = "@" + libTag(li.name);
    });
    const brand = () => { li.notes = brandNotes(li.brand || {}); save(); };
    d.querySelectorAll("[data-b]").forEach(x => x.onchange = () => { (li.brand ||= {})[x.dataset.b] = x.value.trim(); brand(); });
    d.querySelectorAll("[data-c]").forEach(x => x.onchange = () => { li.brand.colours[+x.dataset.c] = x.value; brand(); });
    const input = d.querySelector("input[type=file]");
    d.querySelector(".add").onclick = () => input.click();
    input.onchange = async () => {
      for (const f of input.files) { try { (li.files ||= []).push(await upload(f)); } catch (e) { toast(e.message); } }
      save(); drawLibrary();
    };
    d.querySelectorAll(".thumb button").forEach(x => x.onclick = () => { li.files = li.files.filter(u => u !== x.parentNode.dataset.u); save(); drawLibrary(); });
    d.onclick = e => {
      const a = e.target.closest("[data-a]")?.dataset.a; if (!a) return;
      if (a === "del" && confirm(`Remove “${li.name}” from the Library?`)) { ACC.library.splice(i, 1); save(); drawLibrary(); }
      if (a === "addc") { ((li.brand ||= {}).colours ||= []).push("#3ccf8e"); brand(); drawLibrary(); }
      if (a === "set") photoSet(li);
      if (a === "train") trainIdentity(li);
      if (a === "useid") { show("create"); C.pick(byId("fal-ai/flux-lora"), { prompt: `photo of ${li.trigger}, `, loras: [{ path: li.lora, scale: 1 }] }); toast(`Keep “${li.trigger}” in the prompt: it's what calls up ${li.name}'s face.`, 6000); }
    };
    list.append(d);
  });
}
$("#libAdd").onclick = () => { ACC.library.push({ id: Date.now().toString(36), name: "New " + (ACC.library.length + 1), kind: "character", files: [], notes: "" }); keep("library"); drawLibrary(); };
$("#brief").onchange = () => { ACC.settings.brief = $("#brief").value.trim(); keep("settings"); };
$("#briefOn").onchange = () => { ACC.settings.brief_on = $("#briefOn").checked; keep("settings"); toast(ACC.settings.brief_on ? "The brief is now added to every prompt." : "Brief off."); };
$("#libRules").onchange = e => { const k = e.target.dataset.rule; if (k) { (ACC.settings.rules ||= {})[k] = e.target.checked; keep("settings"); } };

// Photo set: one character, many scenes, same face (opens in Batch, ready to run)
const PHOTO_SET = ["candid street-style photo in a busy city at golden hour", "sitting in a cosy café by the window, soft morning light", "on a beach at sunset, wind in the hair, film photo", "mirror selfie in a modern apartment",
  "hiking on a mountain trail, wide shot, bright daylight", "at a neon-lit night market, shallow depth of field", "close-up portrait in a studio with a coloured backdrop", "laughing with friends at a rooftop party, flash photo",
  "reading on a sofa at home, warm lamp light, candid", "walking a dog in a park in autumn", "at the gym mid-workout, natural light", "driving a car, seen through the side window", "at a concert in the crowd, colourful stage lights",
  "cooking in a sunlit kitchen", "travel photo in front of a famous landmark, wide angle"];
async function photoSet(li) {
  if (!li.files?.length && !li.lora) return toast("Add a few reference photos of this character first.");
  const m = li.lora ? byId("fal-ai/flux-lora") : ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit", "fal-ai/nano-banana-pro/edit"].map(byId).find(Boolean);
  if (!m) return toast("The photo-set model isn't available right now.");
  show("batch");
  await B.pick(m, li.lora ? { loras: [{ path: li.lora, scale: 1 }] } : {});
  $("#bLines").value = PHOTO_SET.map(x => li.lora ? `photo of ${li.trigger}, ${x}` : `@${libTag(li.name)}: ${x}. Same person, same face.`).join("\n");
  $("#bCopies").value = 1; batchSoon();
  toast(`${PHOTO_SET.length} scenes of ${li.name} are ready. Edit them, then press Run.`, 6000);
}
// a personal identity: a FLUX LoRA trained on the character's photos
async function trainIdentity(li) {
  const TRAINER = "fal-ai/flux-lora-fast-training";
  if ((li.files || []).length < 4) return toast("Add at least 4 photos. 10-20 varied, clear photos of the face work best.");
  if (!byId(TRAINER)) return toast("Identity training isn't available right now.");
  const trigger = "ohwx " + libTag(li.name).toLowerCase(), input = { images_data_url: "", trigger_word: trigger, create_masks: true, steps: 1000 };
  let price = ""; try { price = money((await quote(TRAINER, input)).price); } catch {}
  if (!confirm(`Train an identity for ${li.name} from ${li.files.length} photos?\n\nIt costs ${price || "the trainer's price"} and takes 5-10 minutes. Keep this page open until it's done. Afterwards “Use trained identity” and Photo set keep the face consistent.`)) return;
  try {
    toast("Packing the photos…");
    const files = await Promise.all(li.files.map(async (u, i) => ({ name: `${i + 1}.${ext(u) || "jpg"}`, data: new Uint8Array(await (await fetch(u)).arrayBuffer()) })));
    input.images_data_url = await upload(new File([zip(files)], libTag(li.name) + ".zip", { type: "application/zip" }));
    li.trainRun = true; li.trigger = trigger; drawLibrary();
    const run = await launch(TRAINER, input, `Identity · ${li.name}`);
    li.trainRun = false;
    const r = run.result || {}; li.lora = (r.diffusers_lora_file || r.lora_file || {}).url || li.lora;
    keep("library"); drawLibrary();
    toast(run.status === "done" && li.lora ? `${li.name}'s identity is ready.` : `Training didn't work${run.error ? ": " + run.error : ""}. You weren't charged.`, 7000);
  } catch (e) { li.trainRun = false; drawLibrary(); toast(e.message, 6000); }
}
// a .zip of files as they are (no compression): what fal's trainers take
function crc32(b) { let crc = -1; for (let i = 0; i < b.length; i++) { let c = (crc ^ b[i]) & 255; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xEDB88320 : c >>> 1; crc = (crc >>> 8) ^ c; } return (crc ^ -1) >>> 0; }
function zip(files) {
  const parts = [], central = []; let off = 0;
  for (const f of files) {
    const name = new TextEncoder().encode(f.name), crc = crc32(f.data), n = f.data.length;
    const h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint32(14, crc, true); h.setUint32(18, n, true); h.setUint32(22, n, true); h.setUint16(26, name.length, true);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint32(16, crc, true); c.setUint32(20, n, true); c.setUint32(24, n, true); c.setUint16(28, name.length, true); c.setUint32(42, off, true);
    parts.push(h, name, f.data); central.push(c, name); off += 30 + name.length + n;
  }
  const size = central.reduce((a, x) => a + x.byteLength, 0), e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true); e.setUint32(12, size, true); e.setUint32(16, off, true);
  return new Blob([...parts, ...central, e], { type: "application/zip" });
}

// ---------- @name in prompts ----------
// Before a run: the brief and prompt rules are added, and each @name from the Library becomes its reference images (added to the
// model's image inputs) and its description, written the way that model refers to its inputs ("Image 2", "@Image2", "[@reference_image_2]").
const MENTION = /(^|[^\w@\/.\\])@([A-Za-z0-9](?:[\w-]*[A-Za-z0-9])?)/g, MARK = /@\[([^\]]+)\]/g;
const fileFields = s => Object.entries(s.properties || {}).filter(([k, p]) => fileKind(p, k)).map(([k, p]) => ({ k, kind: fileKind(p, k), many: p.type === "array", max: p.maxItems, last: /last|end|tail/.test(k) }));
function mentionStyle(s) {
  const text = Object.entries(s.properties || {}).filter(([k]) => /prompt/i.test(k)).map(([, p]) => p.description || "").join(" ");
  if (/@(Image|Video|Audio)\d/.test(text)) return (kind, n) => `@${kind[0].toUpperCase() + kind.slice(1)}${n}`;
  const m = text.match(/\[(@?)reference_(image|video|audio)_\d\]/);
  if (m) return (kind, n) => `[${kind !== "audio" ? m[1] : ""}reference_${kind}_${n}]`;
  return (kind, n) => `${kind[0].toUpperCase() + kind.slice(1)} ${n}`;
}
async function prepare(model, input) {
  const body = JSON.parse(JSON.stringify(input));
  let s = {}; try { s = await schemaOf(model); } catch {}
  const pk = promptKey(s);
  if (pk && typeof body[pk] === "string" && body[pk].trim()) {
    if (ACC.settings.brief_on && ACC.settings.brief) body[pk] = `${body[pk].trim().replace(/\.$/, "")}. ${ACC.settings.brief}`;
    const extra = Object.entries(RULES).filter(([k, r]) => ACC.settings.rules?.[k] && r.when(body[pk])).map(([, r]) => r.text);
    if (extra.length) body[pk] = body[pk].trim() + "\n\n" + extra.join("\n\n");
  }
  if (!ACC.library.length || !JSON.stringify(body).includes("@")) return body;
  const fields = fileFields(s), isField = new Set(fields.map(f => f.k)), used = [], described = new Set();
  for (const [k, v] of Object.entries(body)) {
    if (typeof v !== "string" || isField.has(k) || !v.includes("@")) continue;
    body[k] = v.replace(MENTION, (m, pre, name) => {
      const li = libItem(name); if (!li) return m;  // not a Library name (an email, a handle): left as typed
      if (li.files?.length) {
        used.push(...li.files);
        let t = li.files.map(f => `@[${f}]`).join(" and ");
        if (li.notes && !described.has(li.name)) { described.add(li.name); t += ` (${li.name}: ${li.notes})`; }
        return pre + t;
      }
      return li.notes ? pre + li.notes : m;
    });
  }
  const present = new Set(fields.flatMap(f => [].concat(body[f.k] ?? [])));
  for (const u of new Set(used)) {
    if (present.has(u)) continue;
    const kind = mediaOf(u), slot = fields.filter(f => f.kind === kind && !f.last).sort((a, b) => b.many - a.many)
      .find(f => f.many ? (body[f.k] || []).length < (f.max || 99) : !body[f.k]);
    if (!slot) throw new Error(`Your prompt mentions a Library element, but ${byId(model)?.name || "this model"} has no free ${kind} input for its pictures. Pick a model that takes ${kind}s, or remove the mention.`);
    body[slot.k] = slot.many ? [...(body[slot.k] || []), u] : u;
  }
  const place = {}, counts = {}, style = mentionStyle(s);
  for (const f of fields) for (const u of [].concat(body[f.k] ?? [])) if (typeof u === "string" && !(u in place)) { counts[f.kind] = (counts[f.kind] || 0) + 1; place[u] = style(f.kind, counts[f.kind]); }
  for (const [k, v] of Object.entries(body)) if (typeof v === "string" && v.includes("@[")) body[k] = v.replace(MARK, (m, u) => place[u] || m);
  return body;
}

// typing @ in any prompt box offers the Library's elements
let MENU = null;
function mentionCheck(ta) {
  const before = ta.value.slice(0, ta.selectionStart), m = before.match(/(^|[^\w@\/.\\])@([\w-]*)$/);
  const items = m ? ACC.library.filter(li => li.name && libTag(li.name).toLowerCase().startsWith(m[2].toLowerCase())).slice(0, 8) : [];
  if (!items.length) { MENU = null; $("#mention").hidden = true; return; }
  MENU = { ta, start: before.length - m[2].length - 1, items, act: 0 };
  drawMenu();
  const r = ta.getBoundingClientRect(), menu = $("#mention");
  Object.assign(menu.style, { left: r.left + scrollX + "px", top: r.bottom + scrollY + 4 + "px", width: Math.min(r.width, 360) + "px" });
}
function drawMenu() {
  $("#mention").hidden = false;
  $("#mention").innerHTML = MENU.items.map((li, i) => `<div class="mitem${i === MENU.act ? " on" : ""}" data-i="${i}">${li.files?.[0] ? `<img src="${esc(li.files[0])}" alt="">` : `<span class="noimg">@</span>`}<div><b>@${esc(libTag(li.name))}</b><span>${esc(LIB_KINDS[li.kind] || "")}${li.files?.length ? ` · ${li.files.length} ${li.files.length === 1 ? "image" : "images"}` : ""}</span></div></div>`).join("");
}
function mentionPick(li) {
  const { ta, start } = MENU, text = `@${libTag(li.name)} `;
  ta.value = ta.value.slice(0, start) + text + ta.value.slice(ta.selectionStart);
  ta.selectionStart = ta.selectionEnd = start + text.length;
  MENU = null; $("#mention").hidden = true; ta.dispatchEvent(new Event("input", { bubbles: true })); ta.focus();
}
document.addEventListener("input", e => { if (e.target.tagName === "TEXTAREA" && e.target.id !== "brief") mentionCheck(e.target); });
document.addEventListener("keydown", e => {
  if (!MENU || e.target !== MENU.ta) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); MENU.act = (MENU.act + (e.key === "ArrowDown" ? 1 : MENU.items.length - 1)) % MENU.items.length; drawMenu(); }
  else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); e.stopImmediatePropagation(); mentionPick(MENU.items[MENU.act]); }
  else if (e.key === "Escape") { MENU = null; $("#mention").hidden = true; }
}, true);
document.addEventListener("focusout", e => { if (MENU && e.target === MENU.ta) setTimeout(() => { MENU = null; $("#mention").hidden = true; }, 150); });
$("#mention").onmousedown = e => { const it = e.target.closest(".mitem"); if (it) { e.preventDefault(); mentionPick(MENU.items[+it.dataset.i]); } };

// ---------- the assistant (charged to credits by what each turn costs) ----------
async function ask(messages, opts = {}) {
  const r = await api("/v1/assist", { messages, ...opts }).catch(e => { if (e.status === 402) openTopup(); throw e; });
  ME.balance -= r.charged; drawBalance();
  return r.message;
}
// one question, one answer: system text, a prompt, and pictures for it to look at
async function write(system, prompt, images = []) {
  const content = images.length ? [{ type: "text", text: prompt }, ...images.map(url => ({ type: "image_url", image_url: { url } }))] : prompt;
  return (await ask([{ role: "system", content: system }, { role: "user", content }])).content || "";
}
function jsonIn(text, open = "[") {
  const close = open === "[" ? "]" : "}", a = text.indexOf(open), b = text.lastIndexOf(close);
  if (a < 0 || b < a) throw new Error("The assistant didn't answer in the expected format. Try again.");
  return JSON.parse(text.slice(a, b + 1));
}

// fill any model's settings from what you mean: { prompt, images, aspect: "16:9", duration }
const SIZE_RATIOS = { square: 1, square_hd: 1, portrait_4_3: 3 / 4, portrait_16_9: 9 / 16, landscape_4_3: 4 / 3, landscape_16_9: 16 / 9 };
const ratioOf = v => { const m = String(v).match(/^(\d+(?:\.\d+)?)\s*[:x×]\s*(\d+(?:\.\d+)?)$/); return m ? m[1] / m[2] : SIZE_RATIOS[v]; };
function aspectFor(p, choice) {
  const r = ratioOf(choice); if (!r || !p) return undefined;
  if (!p.enum) return p.type === "string" ? choice : undefined;
  const opts = p.enum.map(o => [o, ratioOf(o)]).filter(x => x[1]);
  if (!opts.length) return undefined;
  const off = x => Math.abs(Math.log(x / r));
  return opts.reduce((a, b) => off(b[1]) < off(a[1]) ? b : a)[0];
}
function fillFor(s, want) {
  const props = s.properties || {}, out = {}, pk = promptKey(s);
  if (pk && want.prompt) out[pk] = want.prompt;
  for (const [kind, vals] of [["image", want.images], ["video", want.videos], ["audio", want.audios]]) {
    const left = [...(vals || [])];
    for (const f of fileFields(s).filter(f => f.kind === kind && !f.last)) {
      if (!left.length) break;
      out[f.k] = f.many ? left.splice(0, f.max || 99) : left.shift();
    }
  }
  const ak = Object.keys(props).find(k => /^(aspect_ratio|ratio|aspect)$/.test(k)) || (props.image_size ? "image_size" : null);
  if (want.aspect && ak) { const v = aspectFor(props[ak], want.aspect); if (v != null) out[ak] = v; }
  const d = props.duration;
  if (want.duration && d) {
    if (d.enum) { const best = d.enum.reduce((a, b) => Math.abs(parseFloat(b) - want.duration) < Math.abs(parseFloat(a) - want.duration) ? b : a); out.duration = best; }
    else out.duration = d.type === "string" ? String(want.duration) : Number(want.duration);
  }
  return out;
}
// a text-to-image model given pictures: its edit version when there is one (nano-banana-2 -> nano-banana-2/edit)
async function modelFor(id, needsImages) {
  if (!needsImages || fileFields(await schemaOf(id)).some(f => f.kind === "image")) return id;
  return [id + "/edit", id.replace(/text-to-(image|video)$/, (m, k) => k === "video" ? "image-to-video" : "edit")].find(m => m !== id && byId(m)) || id;
}
// a small model chooser: a button that opens the shared list (filtered), remembering the pick in obj[key]
function chooser(el, obj, key, filter, save) {
  const draw = () => el.querySelector(".chosen").innerHTML = chosenHtml(byId(obj[key]));
  el.innerHTML = `<div class="picker"><div class="chosen" tabindex="0"></div></div>`; draw();
  el.querySelector(".chosen").onclick = () => openDrop(el.firstChild, filter, m => { obj[key] = m.id; save(); draw(); });
}
const isImageModel = m => /image/.test(m.cat) && !/video|3d|json/.test(m.cat), isVideoModel = m => /image-to-video|reference-to-video/.test(m.cat + m.id);

// ---------- Storyboard: a film planned scene by scene ----------
const STORY = Object.assign({ script: "", n: 6, imageModel: "fal-ai/nano-banana-2", videoModel: "fal-ai/kling-video/v3/standard/image-to-video", aspect: "16:9", duration: 5, chain: true, scenes: [] }, JSON.parse(store.get("ml_story") || "{}"));
STORY.scenes.forEach(sc => sc.keyBusy = sc.vidBusy = false);  // a run still going when the page closed shows up in History instead
const saveSB = () => store.set("ml_story", JSON.stringify(STORY));
function drawStory() {
  $("#sbScript").value = STORY.script; $("#sbN").value = STORY.n; $("#sbAsp").value = STORY.aspect; $("#sbDur").value = STORY.duration; $("#sbChain").checked = STORY.chain;
  if (!byId(STORY.imageModel)) STORY.imageModel = ["fal-ai/nano-banana-2", "fal-ai/nano-banana", "fal-ai/flux/dev"].find(byId) || STORY.imageModel;
  if (!byId(STORY.videoModel)) STORY.videoModel = MODELS.find(isVideoModel)?.id || STORY.videoModel;
  chooser($("#sbImg"), STORY, "imageModel", isImageModel, saveSB);
  chooser($("#sbVid"), STORY, "videoModel", isVideoModel, saveSB);
  drawScenes();
}
function drawScenes() {
  const box = $("#sbScenes"); box.innerHTML = STORY.scenes.length ? "" : `<p class="muted">No scenes yet. Write the story and press “Write the scenes”, or add them yourself.</p>`;
  STORY.scenes.forEach((sc, i) => {
    const d = document.createElement("div"); d.className = "step";
    const media = (u, busy, label) => u ? (isVideo(u) ? `<video src="${esc(u)}#t=0.1" muted controls preload="metadata" playsinline></video>` : `<img src="${esc(u)}" alt="">`) : `<span class="muted">${busy ? `Making ${label}…` : label}</span>`;
    d.innerHTML = `<div class="stephead"><b>Scene ${i + 1}</b><span class="grow"></span><button class="btn small ghost" data-a="up">↑</button><button class="btn small ghost" data-a="down">↓</button><button class="btn small ghost" data-a="del">✕</button></div>
      <label class="field">What we see<textarea data-f="prompt" placeholder="Who, where, framing, light">${esc(sc.prompt || "")}</textarea></label>
      <label class="field">Camera and action for the video<span class="hint">Optional</span><textarea data-f="motion" style="min-height: 60px" placeholder="e.g. she turns to the window, slow dolly in">${esc(sc.motion || "")}</textarea></label>
      <div class="scenemedia"><div>${media(sc.key, sc.keyBusy, "Keyframe")}</div><div>${media(sc.vid, sc.vidBusy, "Video")}</div></div>
      <div class="row"><button class="btn small" data-a="key">Make keyframe</button><button class="btn small" data-a="anim">Animate</button></div>`;
    d.querySelectorAll("[data-f]").forEach(t => t.oninput = () => { sc[t.dataset.f] = t.value; saveSB(); });
    promptHelp(d.querySelector('[data-f="prompt"]'), () => byId(STORY.imageModel));
    promptHelp(d.querySelector('[data-f="motion"]'), () => byId(STORY.videoModel), "motion");
    d.onclick = e => {
      const a = e.target.closest("[data-a]")?.dataset.a; if (!a) return;
      if (a === "up" && i) [STORY.scenes[i - 1], STORY.scenes[i]] = [sc, STORY.scenes[i - 1]];
      if (a === "down" && i < STORY.scenes.length - 1) [STORY.scenes[i + 1], STORY.scenes[i]] = [sc, STORY.scenes[i + 1]];
      if (a === "del") STORY.scenes.splice(i, 1);
      if (a === "key") return makeKey(sc);
      if (a === "anim") return animate(sc);
      saveSB(); drawScenes();
    };
    box.append(d);
  });
}
$("#sbScript").oninput = () => { STORY.script = $("#sbScript").value; saveSB(); };
$("#sbN").onchange = () => { STORY.n = Math.max(1, Math.min(30, +$("#sbN").value || 6)); saveSB(); };
$("#sbAsp").onchange = () => { STORY.aspect = $("#sbAsp").value; saveSB(); };
$("#sbDur").onchange = () => { STORY.duration = +$("#sbDur").value; saveSB(); };
$("#sbChain").onchange = () => { STORY.chain = $("#sbChain").checked; saveSB(); };
$("#sbAdd").onclick = () => { STORY.scenes.push({ id: Date.now().toString(36), prompt: "", motion: "" }); saveSB(); drawScenes(); };
$("#sbWrite").onclick = async () => {
  if (!STORY.script.trim()) return toast("Write the story first.");
  if (STORY.scenes.some(sc => sc.prompt) && !confirm("Replace the current scenes?")) return;
  $("#sbStat").textContent = "Writing…";
  try {
    const text = await write("You are a film director and storyboard artist. Reply with only JSON, no other text.",
      `Split this story into exactly ${STORY.n} shots for a ${STORY.aspect} film. Reply with a JSON array of ${STORY.n} objects: {"image": a vivid description of the shot's first frame (who, where, framing, lens, lighting, mood), "motion": what moves and how the camera moves during the shot}. If the story uses @Names, keep each exactly as written and use it each time that character or thing appears. Never invent new @Names.\n\nStory:\n${STORY.script}`);
    STORY.scenes = jsonIn(text).slice(0, STORY.n).map((x, k) => ({ id: Date.now().toString(36) + k, prompt: String(x.image || x.prompt || x), motion: String(x.motion || "") }));
    saveSB(); drawScenes(); $("#sbStat").textContent = `${STORY.scenes.length} scenes written. Edit anything, then make the keyframes.`;
  } catch (e) { $("#sbStat").textContent = ""; toast(e.message, 8000); }
};
async function makeKey(sc) {
  const i = STORY.scenes.indexOf(sc), prev = STORY.chain && i > 0 ? STORY.scenes[i - 1].key : null;
  let prompt = (sc.prompt || "").trim();
  if (!prompt) { toast(`Scene ${i + 1} needs a description.`); return false; }
  if (prev) prompt += "\n\nSame characters, place and look as the previous shot (the reference image).";
  try {
    const model = await modelFor(STORY.imageModel, !!prev || /(^|\s)@\w/.test(prompt)), s = await schemaOf(model);
    sc.keyBusy = true; drawScenes();
    const run = await launch(model, fillFor(s, { prompt, images: prev ? [prev] : [], aspect: STORY.aspect }), `Storyboard · scene ${i + 1}`);
    sc.keyBusy = false;
    if (run.status !== "done") { drawScenes(); toast(`Scene ${i + 1}: ${run.error || "it didn't work"}. You weren't charged.`, 7000); return false; }
    Object.assign(sc, { key: run.outputs[0], vid: null }); saveSB(); drawScenes(); return true;
  } catch (e) { sc.keyBusy = false; drawScenes(); toast(e.message, 7000); return false; }
}
async function animate(sc) {
  const i = STORY.scenes.indexOf(sc);
  if (!sc.key) return toast(`Make scene ${i + 1}'s keyframe first.`);
  try {
    const s = await schemaOf(STORY.videoModel);
    sc.vidBusy = true; drawScenes();
    const run = await launch(STORY.videoModel, fillFor(s, { prompt: (sc.motion || sc.prompt || "").trim(), images: [sc.key], duration: STORY.duration, aspect: STORY.aspect }), `Storyboard · scene ${i + 1} video`);
    sc.vidBusy = false;
    if (run.status === "done") sc.vid = run.outputs[0]; else toast(`Scene ${i + 1}'s video: ${run.error || "it didn't work"}. You weren't charged.`, 7000);
    saveSB(); drawScenes();
  } catch (e) { sc.vidBusy = false; drawScenes(); toast(e.message, 7000); }
}
// with continuity on, each keyframe waits for the one before, so it can follow it
$("#sbKeys").onclick = async () => {
  if (!STORY.scenes.length) return toast("Add scenes first.");
  if (!STORY.chain) return STORY.scenes.forEach(makeKey);
  toast("Making keyframes one after another, so each can follow the last. Keep this page open.", 6000);
  for (const sc of STORY.scenes) if (!(await makeKey(sc))) return;
};
$("#sbAnim").onclick = () => STORY.scenes.filter(sc => sc.key && !sc.vid).forEach(animate);
$("#sbTl").onclick = () => {
  const vids = STORY.scenes.map(sc => sc.vid).filter(Boolean);
  if (!vids.length) return toast("No finished scene videos yet.");
  TL.clips = vids.map(url => ({ url })); saveTL(); show("timeline");
};

// ---------- Marketing: a product and a brief, a whole campaign ----------
const MK_MODES = {
  product: ["Product shot", "Premium studio product photograph of {name}, clean seamless backdrop, soft key light with crisp reflections, commercial catalogue quality."],
  lifestyle: ["Lifestyle", "{name} in use in an authentic everyday setting, natural light, candid editorial lifestyle photography."],
  ugc: ["UGC selfie", "Casual smartphone photo of a real person holding up and showing {name} to the camera, authentic user-generated content look, natural home lighting."],
  ad: ["Ad with headline", "Bold social media advert for {name}, striking composition with clear space for a headline, brand-colour background, high contrast."],
  poster: ["Poster", "Graphic poster design featuring {name}, strong layout with a large typographic area, layered composition, print quality."],
  marketplace: ["Marketplace listing", "{name} centred on a pure white background, e-commerce listing photo, even soft lighting, no props, true-to-life colours."],
  unboxing: ["Unboxing", "Hands unboxing {name} from its packaging on a table, top-down view, the satisfying reveal moment."],
  model: ["On a model", "A model wearing or using {name}, fashion editorial photograph, full body, confident pose."],
};
const MK_HOOKS = ["", "Problem → solution: open on the pain, then the product fixes it", "POV: the viewer is the user in the moment it matters", "Before / after", "Unboxing reveal",
  "Testimonial: a real person's honest reaction", "“Stop scrolling if…” call-out to the exact audience", "Myth-busting: “You've been doing X wrong”", "Social proof: “Why 10,000 people switched”", "Price or offer shock up front", "Satisfying close-up texture or detail"];
const MK_FORMATS = { "1:1": "Square feed", "4:5": "Portrait feed", "9:16": "Story / Reel", "16:9": "Banner / YouTube" };
const MK = Object.assign({ product: [], name: "", brief: "", audience: "", headline: "", hook: "", brandKit: "", modes: ["product", "lifestyle"], formats: ["1:1", "9:16"], n: 1, ai: false,
  model: "fal-ai/nano-banana-2/edit", video: false, videoModel: "fal-ai/kling-video/v3/standard/image-to-video", chat: [], concepts: null, script: "" }, JSON.parse(store.get("ml_mkt") || "{}"));
const saveMK = () => store.set("ml_mkt", JSON.stringify(MK));
function drawMarketing() {
  for (const [id, k] of [["#mkName", "name"], ["#mkAud", "audience"], ["#mkBrief", "brief"], ["#mkHead", "headline"]]) $(id).value = MK[k] || "";
  $("#mkHook").innerHTML = MK_HOOKS.map(h => `<option value="${esc(h)}"${h === MK.hook ? " selected" : ""}>${esc(h || "Let it choose")}</option>`).join("");
  const products = ACC.library.filter(li => li.kind === "product" && li.files?.length), kits = ACC.library.filter(li => li.kind === "brand");
  $("#mkLib").hidden = !products.length;
  $("#mkLib").innerHTML = `<option value="">…or use a Library product</option>` + products.map(li => `<option>${esc(li.name)}</option>`).join("");
  $("#mkBrand").innerHTML = `<option value="">None</option>` + kits.map(li => `<option${li.name === MK.brandKit ? " selected" : ""}>${esc(li.name)}</option>`).join("");
  MK.modes = MK.modes.filter(m => MK_MODES[m]).slice(0, 1); MK.formats = MK.formats.filter(f => MK_FORMATS[f]).slice(0, 1);  // one style and one format per campaign
  if (!MK.modes.length) MK.modes = ["product"]; if (!MK.formats.length) MK.formats = ["1:1"];
  $("#mkModes").innerHTML = Object.entries(MK_MODES).map(([k, [l]]) => `<option value="${k}"${MK.modes[0] === k ? " selected" : ""}>${l}</option>`).join("");
  $("#mkFmts").innerHTML = Object.entries(MK_FORMATS).map(([k, l]) => `<option value="${k}"${MK.formats[0] === k ? " selected" : ""}>${l} (${k})</option>`).join("");
  $("#mkN").value = MK.n; $("#mkAi").checked = MK.ai; $("#mkVid").checked = MK.video; $("#mkVidRow").hidden = !MK.video;
  $("#mkConcepts").hidden = !MK.concepts;
  $("#mkConcepts").firstChild.textContent = MK.concepts ? `Using the producer's ${Object.values(MK.concepts).flat().length} written concepts. ` : "";
  if (!byId(MK.model)) MK.model = ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"].find(byId) || MK.model;
  if (!byId(MK.videoModel)) MK.videoModel = MODELS.find(isVideoModel)?.id || MK.videoModel;
  chooser($("#mkModel"), MK, "model", isImageModel, () => { saveMK(); mkCount(); });
  chooser($("#mkVModel"), MK, "videoModel", isVideoModel, saveMK);
  drawMkPhotos(); drawProducer(); mkCount();
}
function drawMkPhotos() {
  $("#mkPhotos").querySelectorAll(".thumb").forEach(t => t.remove());
  $("#mkPhotoAdd").insertAdjacentHTML("beforebegin", MK.product.map(thumbHtml).join(""));
  $("#mkPhotos").querySelectorAll(".thumb button").forEach(b => b.onclick = () => { MK.product = MK.product.filter(u => u !== b.parentNode.dataset.u); saveMK(); drawMkPhotos(); });
}
const mkCount = () => { const n = MK.modes.length * MK.formats.length * MK.n; $("#mkCount").textContent = `${n} image${n === 1 ? "" : "s"}${MK.video ? ` + ${n} video${n === 1 ? "" : "s"}` : ""}`; };
for (const [id, k] of [["#mkName", "name"], ["#mkAud", "audience"], ["#mkBrief", "brief"], ["#mkHead", "headline"]]) $(id).oninput = e => { MK[k] = e.target.value; saveMK(); };
$("#mkHook").onchange = e => { MK.hook = e.target.value; saveMK(); };
$("#mkBrand").onchange = e => { MK.brandKit = e.target.value; saveMK(); };
$("#mkLib").onchange = e => { const li = ACC.library.find(x => x.name === e.target.value); if (li) { MK.product = [...li.files].slice(0, 5); MK.name = MK.name || li.name; saveMK(); drawMarketing(); } };
$("#mkModes").onchange = () => { MK.modes = [$("#mkModes").value]; saveMK(); mkCount(); };
$("#mkFmts").onchange = () => { MK.formats = [$("#mkFmts").value]; saveMK(); mkCount(); };
$("#mkN").onchange = () => { MK.n = Math.max(1, Math.min(6, +$("#mkN").value || 1)); saveMK(); mkCount(); };
$("#mkAi").onchange = () => { MK.ai = $("#mkAi").checked; saveMK(); };
$("#mkVid").onchange = () => { MK.video = $("#mkVid").checked; $("#mkVidRow").hidden = !MK.video; saveMK(); mkCount(); };
$("#mkClear").onclick = e => { e.preventDefault(); MK.concepts = null; MK.script = ""; saveMK(); drawMarketing(); };
$("#mkPhotoAdd").onclick = () => $("#mkFile").click();
$("#mkFile").onchange = async () => {
  for (const f of $("#mkFile").files) { if (MK.product.length >= 5) break; try { MK.product.push(await upload(f)); } catch (e) { toast(e.message); } }
  $("#mkFile").value = ""; saveMK(); drawMkPhotos();
};
$("#mkImport").onclick = async () => {
  const url = $("#mkUrl").value.trim(); if (!url) return;
  $("#mkImport").textContent = "Importing…";
  try {
    const r = await api("/v1/product", { url });
    if (r.name) MK.name = r.name; if (r.description) MK.brief = r.description; if (r.images.length) MK.product = r.images;
    saveMK(); drawMarketing(); toast(`Imported ${r.name || "the product"}${r.images.length ? ` with ${r.images.length} photo${r.images.length === 1 ? "" : "s"}` : ", but no photos: upload some"}.`, 6000);
  } catch (e) { toast(e.message, 8000); }
  $("#mkImport").textContent = "Import";
};
// the ad producer: asks a few questions, then writes the brief and concepts
function drawProducer() {
  const log = $("#prodLog"), last = MK.chat.at(-1);
  log.innerHTML = MK.chat.map(m => `<div class="am ${m.role === "user" ? "user" : "bot"}">${esc(m.content.replace(/BRIEF:[\s\S]*$/, "").trim() || "Here's the brief.")}</div>`).join("");
  if (last?.role === "assistant" && last.content.includes("BRIEF:")) {
    log.insertAdjacentHTML("beforeend", `<button class="btn small primary" id="prodApply">Apply the brief to the campaign</button>`);
    $("#prodApply").onclick = () => {
      try {
        const b = jsonIn(last.content.slice(last.content.indexOf("BRIEF:")), "{");
        const modes = (b.modes || []).filter(m => MK_MODES[m]), formats = (b.formats || []).filter(f => MK_FORMATS[f]);
        Object.assign(MK, { name: b.name || MK.name, audience: b.audience || MK.audience, brief: b.brief || MK.brief, headline: b.headline || MK.headline, hook: b.hook || MK.hook,
          modes: modes.length ? modes.slice(0, 1) : MK.modes, formats: formats.length ? formats.slice(0, 1) : MK.formats, video: !!b.video,
          concepts: b.concepts && Object.keys(b.concepts).length ? b.concepts : null, script: b.script || "" });
        MK.n = Math.max(1, ...Object.values(MK.concepts || {}).map(a => a.length || 1)); saveMK(); drawMarketing();
        toast("Brief applied. Add product photos if you haven't, then create the campaign.", 6000);
      } catch (e) { toast(e.message); }
    };
  }
  log.hidden = !MK.chat.length; log.scrollTop = log.scrollHeight;
}
const PRODUCER = "You are a sharp ad producer at a performance-marketing studio. Help the user turn their product into an ad campaign. "
  + "Ask ONE short question at a time (at most four in total) about whatever is still unclear: what makes the product special, who it's for, "
  + "the goal or offer, the hook, and video or still (and which platform). Suggest options when it helps. Be brief and friendly. "
  + "When you know enough, or the user says go, reply with one sentence followed by a line starting with BRIEF: and then JSON only: "
  + '{"name": str, "audience": str, "brief": str, "headline": str, "hook": str, "modes": [the one best of "product","lifestyle","ugc","ad","poster","marketplace","unboxing","model"], '
  + '"formats": [the one best of "1:1","4:5","9:16","16:9"], "video": true/false, "concepts": {"<mode>": ["a vivid, specific image prompt that refers to the product as the product in the reference images", ...]}, '
  + '"script": "for video ads, a short shot list with the hook in the first second"}.';
async function producerSend() {
  const text = $("#prodIn").value.trim(); if (!text) return;
  MK.chat.push({ role: "user", content: text }); $("#prodIn").value = ""; saveMK(); drawProducer();
  $("#prodLog").insertAdjacentHTML("beforeend", `<div class="am bot muted">Thinking…</div>`);
  try {
    const known = `Product so far: name=${MK.name || "?"}; details=${MK.brief || "?"}; photos=${MK.product.length}.`;
    const reply = await ask([{ role: "system", content: PRODUCER + "\n\n" + known }, ...MK.chat.slice(-20)]);
    MK.chat.push({ role: "assistant", content: (reply.content || "").trim() });
  } catch (e) { MK.chat.pop(); toast(e.message, 8000); }
  saveMK(); drawProducer();
}
$("#prodSend").onclick = producerSend;
$("#prodIn").onkeydown = e => { if (e.key === "Enter") producerSend(); };
$("#prodNew").onclick = () => { MK.chat = []; saveMK(); drawProducer(); };
$("#mkGo").onclick = async () => {
  if (!MK.product.length) return toast("Add at least one product photo.");
  if (!MK.modes.length || !MK.formats.length) return toast("Pick at least one style and one format.");
  const name = MK.name.trim() || "the product", keepLook = " The product must look exactly like the one in the reference images: same shape, colours, materials, logo and label.";
  const kit = MK.brandKit && ACC.library.find(li => li.kind === "brand" && li.name === MK.brandKit);
  const extra = (MK.brief.trim() ? ` ${MK.brief.trim().replace(/\.?$/, ".")}` : "") + (MK.audience.trim() ? ` Made for ${MK.audience.trim()}.` : "") + (kit ? ` Follow the brand kit @${libTag(kit.name)}.` : "");
  const headline = m => MK.headline.trim() && ["ad", "poster"].includes(m) ? ` Include the headline “${MK.headline.trim()}” in clean, bold, correctly spelled typography.` : "";
  let concepts = MK.concepts || {};
  $("#mkGo").disabled = true;
  try {
    if (MK.ai && !MK.concepts) {
      $("#mkCount").textContent = "Writing concepts…";
      concepts = jsonIn(await write("You are an award-winning advertising creative director. Reply with only JSON, no other text.",
        `Product: ${name}. Brief: ${MK.brief || "-"}. Audience: ${MK.audience || "-"}.\nFor each style below write ${MK.n} distinct, specific image-generation prompts for campaign images (scene, model if any, setting, composition, lighting, mood). Refer to the product as "the product in the reference images".\nStyles: ${MK.modes.map(m => `${m} = ${MK_MODES[m][0]}`).join("; ")}.\nReply as a JSON object: {"<style key>": ["prompt", …], …}.`, MK.product.slice(0, 2)), "{");
    }
    const variety = ["", " A fresh composition and a different camera angle.", " A different setting and colour palette.", " Shot from a dramatic low angle.", " A minimal composition with lots of negative space.", " Warm golden-hour light."];
    const model = await modelFor(MK.model, true), s = await schemaOf(model), runs = [];
    for (const m of MK.modes) for (let v = 0; v < MK.n; v++) {
      const hook = MK.hook && ["ad", "ugc", "poster", "unboxing"].includes(m) ? ` The hook: ${MK.hook}.` : "";
      const prompt = (concepts[m]?.[v] || MK_MODES[m][1].replaceAll("{name}", name) + variety[v % variety.length]) + hook + extra + headline(m) + keepLook;
      for (const f of MK.formats) runs.push(fillFor(s, { prompt, images: MK.product.slice(0, 5), aspect: f }));
    }
    const per = runs.length * (MK.video ? 2 : 1);
    if (per > 10 && !confirm(`This starts ${runs.length} images${MK.video ? ` and ${runs.length} videos` : ""}, each charged. Continue?`)) return;
    const vs = MK.video ? await schemaOf(MK.videoModel) : null;
    const motion = (MK.script ? MK.script + " " : MK.hook ? `Hook in the first second: ${MK.hook}. ` : "") + "Smooth cinematic advert shot, subtle natural motion, the product stays exactly the same";
    toast(`Started ${runs.length} campaign image${runs.length === 1 ? "" : "s"}. They appear under Latest.`, 6000);
    const results = await Promise.allSettled(runs.map((input, i) => vs
      ? chain([{ model, input }, { model: MK.videoModel, input: fillFor(vs, { prompt: motion, images: [PREV], duration: 5 }) }], `Campaign ${i + 1}`)
      : launch(model, input, `Campaign ${i + 1}`)));
    const failed = results.find(r => r.status === "rejected"); if (failed) toast(failed.reason.message, 7000);
  } catch (e) { toast(e.message, 8000); }
  finally { $("#mkGo").disabled = false; mkCount(); }
};

// ---------- scroll-stop score: would this stop the scroll? ----------
async function grabFrames(url, times = [0, 0.7, 1.5, 3]) {
  const v = document.createElement("video"); v.crossOrigin = "anonymous"; v.src = url; v.muted = true; v.preload = "auto";
  await new Promise((ok, bad) => { v.onloadeddata = ok; v.onerror = () => bad(new Error("Couldn't read the video.")); });
  const out = [];
  for (const t of times.filter(t => t < (v.duration || 99))) {
    v.currentTime = t; await new Promise(r => v.onseeked = r);
    const c = document.createElement("canvas"), sc = Math.min(1, 768 / Math.max(v.videoWidth, v.videoHeight)); c.width = v.videoWidth * sc; c.height = v.videoHeight * sc;
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    out.push(await upload(new File([await new Promise(r => c.toBlob(r, "image/jpeg", 0.85))], `frame_${t}.jpg`, { type: "image/jpeg" })));
  }
  return out;
}
async function scoreIt(u, box) {
  const video = isVideo(u);
  box.innerHTML = `<label class="field">What is it for?<span class="hint">Optional, e.g. TikTok ad for a running shoe, women 25-40</span><input id="scCtx"></label><button class="btn small primary" id="scGo">Score it</button>`;
  $("#scGo").onclick = async () => {
    const context = $("#scCtx").value.trim();
    box.innerHTML = `<p class="muted">Looking${video ? " at the first 3 seconds" : ""}…</p>`;
    try {
      const images = video ? await grabFrames(u) : [u];
      const what = video ? "the first seconds of a short video (frames in order)" : "an image for social media or an ad";
      const r = jsonIn(await write("You are a senior social media creative strategist who scores content for scroll-stopping power. Reply with only JSON.",
        `Score ${what}. Context from the creator: ${context || "none"}.\nReply as JSON: {"hook": 0-100 (would it stop the scroll in the first second), "clarity": 0-100 (is the subject and message instantly clear), "emotion": 0-100, "composition": 0-100 (framing, contrast, focal point, readable on a phone), "platform_fit": 0-100 (native to TikTok/Reels/Feed), "overall": 0-100, "verdict": one sentence, "strengths": [up to 3 short points], "fixes": [up to 4 specific, actionable changes]}`, images), "{");
      const bar = (l, v) => `<div class="scorebar"><span>${l}</span><span><i style="width: ${Math.max(3, +v || 0)}%"></i></span><b>${+v || 0}</b></div>`;
      box.innerHTML = `<div class="row"><span class="bigscore">${+r.overall || 0}</span><span class="grow">${esc(r.verdict || "")}</span></div>
        ${bar("Hook", r.hook)}${bar("Clarity", r.clarity)}${bar("Emotion", r.emotion)}${bar("Composition", r.composition)}${bar("Platform fit", r.platform_fit)}
        ${r.strengths?.length ? `<b>Working</b><ul>${r.strengths.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${r.fixes?.length ? `<b>Make it stronger</b><ul>${r.fixes.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
    } catch (e) { box.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  };
}

// ---------- the assistant chat: finds models, prices them, and runs them when you approve ----------
const CHAT = JSON.parse(store.get("ml_chat") || '{"messages": [], "auto": false}');
const saveChat = () => store.set("ml_chat", JSON.stringify({ ...CHAT, messages: CHAT.messages.slice(-60) }));
let chatImages = [], chatBusy = false;
const SYSTEM = () => `You are the assistant inside Muselight's web app (muselight.studio), where people make images, video, voice and music with over a thousand AI models, paid from one prepaid balance (Muselight Credits).
Help them pick models, write prompts and settings, and run things. Be brief, friendly and specific; use plain words.
Always find a model's exact id with search_models before using it in another tool; never guess ids.
Tools: search_models finds models; model_settings shows a model's settings; price checks a run's exact price; run_model starts a run and uses their credits; recent_results lists what they made; library lists their saved characters, products, places, styles and brand kits.
In prompts, @Name refers to a Library element: Muselight sends its reference images and description with the run.
The app's Create menu: Start (Guided, Simple, Apps: one-click tools for a result), Images (Generate, Edit, Sketch, Variations, Compare models), Video (Generate, Film: scene by scene, Editor: join clips and add a soundtrack), Audio (Voice, Music, Sound effects, Voice clone, Lip sync), Social (Story series: viral multi-part drama; AI influencer), Business (Ads), Advanced (Pipelines: chained steps). Also Library and History.
${CHAT.auto ? "Auto-run is on: when they ask for something, run it straight away without asking first." : "run_model shows the person an approval card with the exact price, so when they ask for something, call it straight away; don't ask them to confirm in words first."}
Their balance is $${(ME?.balance ?? 0).toFixed(2)}.`;
const TOOLS = [
  ["search_models", "Find models by what they do or their name. Returns id, name, category and list price.", { query: { type: "string" }, kind: { type: "string", enum: ["image", "video", "audio", "any"] } }, ["query"]],
  ["model_settings", "A model's settings: names, types, choices, defaults and which are required.", { model: { type: "string" } }, ["model"]],
  ["price", "The exact price of a run with these settings.", { model: { type: "string" }, input: { type: "object" } }, ["model", "input"]],
  ["run_model", "Start a run with these settings and wait for its results. Costs credits.", { model: { type: "string" }, input: { type: "object" } }, ["model", "input"]],
  ["recent_results", "The person's latest results, newest first.", { count: { type: "integer" } }, []],
  ["library", "The person's Library elements (names to use as @Name).", {}, []],
].map(([name, description, properties, required]) => ({ type: "function", function: { name, description, parameters: { type: "object", properties, required } } }));
async function runTool(name, a) {
  if (a.model && !byId(a.model)) return { error: `There's no model with the id "${a.model}". Call search_models to find its exact id.` };
  if (name === "search_models") {
    const q = String(a.query || "").toLowerCase().split(/\s+/).filter(Boolean);
    return MODELS.filter(m => (!a.kind || a.kind === "any" || kind(m) === a.kind) && q.every(w => ((m.name || "") + " " + m.id + " " + m.cat + " " + (m.desc || "")).toLowerCase().includes(w)))
      .slice(0, 12).map(m => ({ id: m.id, name: m.name, category: m.cat, price: money(m.cost.usd) + unit(m.cost) }));
  }
  if (name === "model_settings") {
    const s = await schemaOf(a.model);
    return { required: s.required || [], settings: Object.fromEntries(Object.entries(s.properties || {}).map(([k, p]) => [k, { type: p.type || (fileKind(p, k) ? "file url" : ""), ...(p.enum ? { choices: p.enum } : {}), ...(p.default != null ? { default: p.default } : {}), ...(fileKind(p, k) ? { file: fileKind(p, k) } : {}), description: (p.description || "").slice(0, 160) }])) };
  }
  if (name === "price") return { price: money((await quote(a.model, a.input || {})).price) };
  if (name === "run_model") {
    const q = await quote(a.model, a.input || {}).catch(e => ({ error: e.message }));
    if (q.error) return { error: q.error };
    if (!CHAT.auto && !(await approve(a.model, a.input || {}, q.price))) return { declined: "The person declined this run." };
    const run = await launch(a.model, a.input || {}, "Assistant");
    return run.status === "done" ? { status: "done", charged: money(run.charged || 0), outputs: run.outputs } : { status: run.status, error: run.error, note: "You weren't charged." };
  }
  if (name === "recent_results") return HIST.filter(r => r.status === "done").slice(0, Math.min(20, a.count || 8)).map(r => ({ model: r.model, prompt: promptText(r).slice(0, 200), outputs: (r.outputs || []).slice(0, 4) }));
  if (name === "library") return ACC.library.map(li => ({ name: "@" + libTag(li.name), kind: li.kind, description: li.notes || "", images: (li.files || []).length }));
  return { error: "Unknown tool." };
}
// an approval card in the chat: resolves true when the person approves
function approve(model, input, price) {
  return new Promise(ok => {
    const d = document.createElement("div"); d.className = "am approve";
    d.innerHTML = `<b>Run ${esc(byId(model)?.name || model)} for ${money(price)}?</b><div class="ap">${esc(Object.entries(input).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join("\n"))}</div>
      <div class="row"><button class="btn small primary" data-ok="1">Approve</button><button class="btn small" data-ok="0">Decline</button></div>`;
    d.onclick = e => { const b = e.target.closest("[data-ok]"); if (!b) return; d.querySelector(".row").innerHTML = b.dataset.ok === "1" ? `<span class="ok">Approved</span>` : `<span class="muted">Declined</span>`; ok(b.dataset.ok === "1"); };
    $("#chatLog").append(d); $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
  });
}
function mdLite(t) {  // small, safe markdown: code, bold, bullets, paragraphs, and links to results shown as pictures
  const inline = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  const blocks = String(t).split(/\n{2,}/).map(b => {
    const lines = b.split("\n");
    return lines.every(l => /^\s*(?:[-*•]|\d+[.)])\s+/.test(l)) ? `<ul>${lines.map(l => `<li>${inline(l.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, ""))}</li>`).join("")}</ul>` : `<p>${lines.map(inline).join("<br>")}</p>`;
  }).join("");
  const media = [...new Set(String(t).match(/https:\/\/[^\s)"'`]+\.(?:png|jpe?g|webp|mp4|webm)/gi) || [])];
  return blocks + (media.length ? `<div class="chatmedia">${media.map(u => mediaHtml(u)).join("")}</div>` : "");
}
function drawChat() {
  const log = $("#chatLog");
  const shown = CHAT.messages.filter(m => (m.role === "user" || m.role === "assistant") && (m.content || m.images) || m.media);
  log.innerHTML = shown.length ? shown.map(m => m.media ? `<div class="am bot"><div class="chatmedia">${m.media.map(u => mediaHtml(u)).join("")}</div></div>` : m.role === "user"
    ? `<div class="am user">${esc(typeof m.content === "string" ? m.content : m.content.find(p => p.type === "text")?.text || "")}${(m.images || []).length ? `<div class="chatmedia">${m.images.map(u => mediaHtml(u)).join("")}</div>` : ""}</div>`
    : `<div class="am bot">${mdLite(m.content)}</div>`).join("")
    : `<div class="chatempty"><b>How can I help?</b><span>I can find the right model, write prompts, check prices and run things for you, asking before each run.</span>
       ${["Make a cinematic photo of a lighthouse at dusk", "Which video model is best for product ads?", "Turn my last image into a 5-second video"].map(t => `<button class="btn small ghost">${esc(t)}</button>`).join("")}</div>`;
  log.querySelectorAll(".chatempty button").forEach(b => b.onclick = () => { $("#chatIn").value = b.textContent; $("#chatIn").focus(); });
  if (chatBusy) log.insertAdjacentHTML("beforeend", `<div class="am bot muted">${esc(chatBusy === true ? "Thinking…" : chatBusy)}</div>`);
  log.scrollTop = log.scrollHeight;
  $("#chatAuto").checked = CHAT.auto;
}
async function chatSend() {
  const text = $("#chatIn").value.trim(); if ((!text && !chatImages.length) || chatBusy) return;
  const content = chatImages.length ? [{ type: "text", text: text || "(see the attached pictures)" }, ...chatImages.map(url => ({ type: "image_url", image_url: { url } }))] : text;
  CHAT.messages.push({ role: "user", content, images: chatImages.length ? [...chatImages] : undefined });
  $("#chatIn").value = ""; chatImages = []; drawChatAtt(); chatBusy = true; drawChat();
  try {
    for (let step = 0; step < 10; step++) {  // the model may call tools several times before it answers
      const recent = CHAT.messages.slice(-40);
      while (recent.length > 1 && recent[0].role !== "user") recent.shift();  // never start halfway through a tool exchange
      const msgs = [{ role: "system", content: SYSTEM() }, ...recent.map(({ images, media, ...m }) => m)];
      const reply = await ask(msgs, { tools: TOOLS });
      CHAT.messages.push({ role: "assistant", content: reply.content || "", ...(reply.tool_calls ? { tool_calls: reply.tool_calls } : {}) });
      if (!reply.tool_calls?.length) break;
      for (const call of reply.tool_calls) {
        let args = {}; try { args = JSON.parse(call.function.arguments || "{}"); } catch {}
        chatBusy = { search_models: "Looking for models…", model_settings: "Reading the model's settings…", price: "Checking the price…", run_model: "Running it…", recent_results: "Looking at your results…", library: "Reading your Library…" }[call.function.name] || "Working…";
        drawChat();
        let result; try { result = await runTool(call.function.name, args); } catch (e) { result = { error: e.message }; }
        CHAT.messages.push({ role: "tool", tool_call_id: call.id, content: JSON.stringify(result).slice(0, 12000), ...(call.function.name === "run_model" && result.outputs ? { media: result.outputs } : {}) });
      }
      chatBusy = true; drawChat();
    }
  } catch (e) { toast(e.message, 7000); }
  chatBusy = false; saveChat(); drawChat();
}
function drawChatAtt() {
  $("#chatAtt").innerHTML = chatImages.map((u, i) => `<div class="thumb" data-i="${i}"><img src="${esc(u)}" alt=""><button type="button">✕</button></div>`).join("");
  $("#chatAtt").querySelectorAll("button").forEach(b => b.onclick = () => { chatImages.splice(+b.parentNode.dataset.i, 1); drawChatAtt(); });
}
$("#chatBtn").onclick = () => { $("#chat").hidden = !$("#chat").hidden; if (!$("#chat").hidden) { drawChat(); $("#chatIn").focus(); } };
$("#chatClose").onclick = () => $("#chat").hidden = true;
$("#chatNew").onclick = () => { if (chatBusy) return; CHAT.messages = []; saveChat(); drawChat(); };
$("#chatAuto").onchange = () => { CHAT.auto = $("#chatAuto").checked; saveChat(); if (CHAT.auto) toast("The assistant can now start runs without asking. Every run uses credits.", 6000); };
$("#chatSend").onclick = chatSend;
$("#chatIn").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !MENU) { e.preventDefault(); chatSend(); } };
$("#chatAttach").onclick = () => $("#chatFile").click();
$("#chatFile").onchange = async () => { for (const f of $("#chatFile").files) { try { chatImages.push(await upload(f)); } catch (e) { toast(e.message); } } $("#chatFile").value = ""; drawChatAtt(); };

// ---------- a small dialog: resolves true when confirmed ----------
function dialog(title, body, ok = "OK") {
  return new Promise(done => {
    const d = document.createElement("div"); d.className = "dlg";
    d.innerHTML = `<div class="box"><h2>${esc(title)}</h2>${body}<div class="row"><button class="btn" data-ok="0" style="flex: 1">Cancel</button><button class="btn primary" data-ok="1" style="flex: 1">${esc(ok)}</button></div></div>`;
    document.body.append(d);
    d.onclick = e => { const b = e.target.closest("[data-ok]"); if (b || e.target === d) { const yes = b?.dataset.ok === "1"; done(yes ? d : null); setTimeout(() => d.remove()); } };
  });
}

// ---------- help on every prompt box: a live checklist, the prompt builder, and Improve my prompt ----------
// Built from the model makers' own guides (Google's Nano Banana and Veo 3.1 guides, Black Forest Labs' FLUX guide, Kling's
// formula): describe the scene in sentences rather than a keyword list; subject and action first; name the shot, light, lens and
// look; say what should be there rather than what shouldn't; in video, one clear action per clip with the camera move as its own
// sentence; from a picture, describe the movement, not what the picture already shows; sound on its own lines.
const promptMode = (m, k = "prompt") => {
  if (!m) return "image";
  const t = (m.cat || "") + " " + m.id;
  if (kind(m) === "audio") return k === "text" ? null : /sound|sfx|foley|effect/.test(t) ? "sfx" : "music";
  if (kind(m) === "video") return /image-to-video|reference|video-to-video|\/edit|avatar|lipsync/.test(t) ? "i2v" : "video";
  return /edit|image-to-image|inpaint|fill|outpaint|redux|kontext/.test(t) ? "edit" : "image";
};
const VIS = ["image", "edit", "video", "i2v"], MOV = ["video", "i2v"];
// [group, tab, modes, options [label, words added to the prompt, what it means in plain words], several allowed]
const BUILD = [
  ["Medium", "Style", VIS, [["Photo", "a realistic photograph", "Looks like a real photo"], ["Cinematic still", "a cinematic film still", "Like a frame from a movie"], ["Product shot", "a clean commercial product photograph", "Advert-style product photo"], ["3D animation", "a polished 3D animated feature-film style render", "Like a modern animated family film"], ["Anime", "a hand-drawn anime illustration with clean line art and cel shading", "Japanese animation style"], ["Illustration", "a detailed digital illustration", "Drawn, not photographed"], ["Oil painting", "a textured oil painting with visible brushstrokes", "Classic painting"], ["Watercolour", "a soft watercolour painting on textured paper", "Soft, washed colours"], ["Claymation", "a stop-motion claymation style with handmade clay textures", "Made of modelling clay"], ["Comic book", "a bold comic-book style with ink outlines and halftone shading", "Graphic-novel look"], ["Pixel art", "detailed 16-bit pixel art", "Retro video-game look"], ["Documentary", "a candid, observational documentary style", "Real and unposed"]]],
  ["Era", "Style", VIS, [["1960s", "a 1960s Technicolor look with rich saturated colour"], ["1970s", "a 1970s look with warm tones and heavy film grain"], ["1980s", "a 1980s look with soft colour and glowing highlights"], ["1990s", "a 1990s film-photo look, slightly faded"], ["2000s", "an early-2000s digital-camera look"], ["Modern", "a clean, modern look"], ["Black & white", "high-contrast black-and-white"]]],
  ["Mood", "Style", VIS, [["Joyful", "a joyful mood"], ["Calm", "a calm, peaceful mood"], ["Tense", "a tense mood"], ["Melancholic", "a melancholic mood"], ["Mysterious", "a mysterious mood"], ["Romantic", "a tender, romantic mood"], ["Epic", "an epic, awe-inspiring mood"], ["Cosy", "a warm, cosy mood"]]],
  ["Shot size", "Shot", VIS, [["Extreme close-up", "an extreme close-up on a detail", "Fills the frame with one detail, like an eye"], ["Close-up", "a close-up on the face", "Head and shoulders"], ["Medium", "a medium shot from the waist up", "Waist up"], ["Full body", "a full-body shot", "Head to toe"], ["Wide", "a wide shot showing the whole setting", "The person small in a big scene"], ["Establishing", "a wide establishing shot of the location", "Shows where we are"], ["Over the shoulder", "an over-the-shoulder shot", "From behind one person, looking at another"]]],
  ["Camera angle", "Shot", VIS, [["Eye level", "at eye level", "Neutral, natural"], ["Low angle", "from a low angle looking up", "Makes the subject feel powerful"], ["High angle", "from a high angle looking down", "Makes the subject feel small"], ["Overhead", "from directly overhead", "Flat lay, bird's-eye"], ["Three-quarter", "in three-quarter view", "Turned slightly, the most flattering angle"], ["Profile", "in side profile"], ["From behind", "from behind the subject"], ["Dutch tilt", "with a tilted, diagonal frame", "Tilted horizon for unease"], ["Point of view", "from the subject's point of view", "Through their eyes"], ["Aerial", "from a high aerial view", "Drone view"]]],
  ["Composition", "Shot", VIS, [["Rule of thirds", "composed on the rule of thirds", "Subject off-centre, balanced"], ["Centred", "centred, symmetrical composition", "Subject dead centre"], ["Negative space", "with generous negative space around the subject", "Lots of empty room, e.g. for text"], ["Leading lines", "with leading lines drawing the eye to the subject"], ["Framed", "framed through a doorway or foreground objects", "Something in front frames the subject"]]],
  ["Camera", "Camera", VIS, [["Cinema camera", "shot on an ARRI Alexa cinema camera", "Hollywood-film quality"], ["Full-frame", "shot on a full-frame mirrorless camera", "Crisp professional photo"], ["Medium format", "shot on a medium-format camera", "Fashion and editorial richness"], ["35mm film", "shot on 35mm film", "Classic film photo"], ["Phone", "shot on a smartphone", "Everyday, social-media feel"], ["Disposable", "shot on a disposable camera with on-camera flash", "Flashy party snapshot"], ["GoPro", "shot on an action camera", "Wide, immersive action view"]]],
  ["Focal length", "Camera", VIS, [["16mm", "a 16mm ultra-wide lens", "Very wide, dramatic perspective"], ["24mm", "a 24mm wide lens", "Wide, shows the surroundings"], ["35mm", "a 35mm lens", "Natural, documentary"], ["50mm", "a 50mm lens", "Like the human eye"], ["85mm", "an 85mm portrait lens", "Flattering portraits"], ["135mm", "a 135mm telephoto lens with compressed background", "Background looks close and big"], ["Macro", "a macro lens", "Tiny details up close"]]],
  ["Aperture", "Camera", VIS, [["f/1.4", "f/1.4 with a very shallow depth of field and creamy blurred background", "Very blurry background"], ["f/2.8", "f/2.8 with a softly blurred background", "Background gently blurred"], ["f/8", "f/8 with sharp detail front to back", "Mostly sharp"], ["f/16", "f/16 with deep focus, everything sharp", "Everything sharp, good for landscapes"]]],
  ["Shutter", "Camera", ["image", "edit"], [["Frozen action", "a fast shutter freezing the motion", "Splashes and jumps frozen mid-air"], ["Motion blur", "a slow shutter with motion blur", "Movement shows as a streak"], ["Long exposure", "a long exposure with light trails", "Car lights as streaks at night"]]],
  ["Film stock", "Camera", VIS, [["Portra 400", "Kodak Portra 400 colours with natural grain", "Warm, soft skin tones"], ["CineStill 800T", "CineStill 800T with red halation around lights", "Moody night film, glowing lights"], ["Fuji Velvia", "Fujifilm Velvia colours, vivid and saturated", "Punchy landscape colour"], ["Ilford HP5", "Ilford HP5 black-and-white film", "Classic black and white"], ["Digital clean", "clean digital colour with no grain", "Modern and crisp"]]],
  ["Grain", "Camera", VIS, [["None", "a clean, smooth digital finish"], ["Fine", "fine, subtle film grain"], ["Heavy", "heavy, gritty film grain"]]],
  ["Lens character", "Camera", VIS, [["Anamorphic", "an anamorphic look with oval bokeh and horizontal lens flares", "Widescreen movie flares"], ["Vintage lens", "a vintage lens with soft, glowing highlights"], ["Tilt-shift", "a tilt-shift miniature effect", "Makes real places look like toys"], ["Fisheye", "a fisheye lens distortion"]]],
  ["Lighting", "Light", VIS, [["Soft window", "soft daylight from a large window to one side"], ["Golden hour", "warm, low golden-hour sunlight with long shadows", "Just before sunset"], ["Blue hour", "the cool, soft light of blue hour", "Just after sunset"], ["Hard sun", "hard midday sun with crisp shadows"], ["Overcast", "soft, even overcast light"], ["Studio softbox", "clean three-point studio softbox lighting", "Professional studio"], ["Rembrandt", "Rembrandt lighting with one high side light and a triangle of light on the shadowed cheek", "Classic dramatic portrait light"], ["Backlit", "strong backlight with a glowing rim around the subject"], ["Neon", "coloured neon light washing the scene"], ["Candlelight", "flickering warm candlelight"], ["Flash", "direct on-camera flash with hard shadows", "Party-photo flash"], ["Light beams", "volumetric light beams through haze", "Visible rays of light"], ["Moonlight", "cool moonlight with deep blue shadows"], ["Silhouette", "a bright background turning the subject into a silhouette"]]],
  ["Time and weather", "Light", VIS, [["Sunrise", "at sunrise"], ["Midday", "at midday"], ["Sunset", "at sunset"], ["Night", "at night"], ["Rain", "in the rain with wet, reflective surfaces"], ["Fog", "in soft fog"], ["Snow", "in falling snow"], ["Storm", "under dark storm clouds"]]],
  ["Colour grade", "Colour", VIS, [["Natural", "natural, true-to-life colour"], ["Warm", "a warm amber colour grade"], ["Cool", "a cool blue colour grade"], ["Teal & orange", "a teal-and-orange grade, warm skin against cool shadows", "Blockbuster-film colours"], ["Muted", "muted, desaturated colours"], ["Vivid", "vivid, saturated colours"], ["Pastel", "a soft pastel palette"], ["Moody", "a dark, moody grade with deep shadows"], ["Bleach bypass", "a gritty bleach-bypass look, low saturation and high contrast", "Gritty war-film look"]]],
  ["Camera move", "Motion", MOV, [["Still camera", "a locked-off, still camera", "Camera doesn't move"], ["Slow push in", "the camera slowly pushes in toward the subject", "Moves closer, builds intensity"], ["Pull back", "the camera slowly pulls back to reveal the scene", "Moves away, reveals more"], ["Follow", "the camera tracks alongside, following the subject"], ["Orbit", "the camera circles around the subject"], ["Pan left", "the camera pans smoothly to the left", "Turns on the spot"], ["Pan right", "the camera pans smoothly to the right"], ["Tilt up", "the camera tilts up"], ["Rise up", "the camera rises up like a crane", "Lifts higher"], ["Drone", "a sweeping aerial drone shot"], ["Handheld", "handheld camera with natural shake", "Real, documentary feel"], ["Smooth glide", "a smooth, floating gimbal move"], ["Zoom in", "a slow zoom in"], ["Crash zoom", "a sudden fast zoom in"], ["Dolly zoom", "a dolly zoom, the background stretching while the subject stays the same size", "The famous 'vertigo' effect"], ["Whip pan", "a fast whip pan"], ["Focus pull", "the focus shifts from the foreground to the background"]], true],
  ["Subject motion", "Motion", MOV, [["Subtle", "subtle, natural movement: breathing, blinking, a slight turn of the head", "Only small movements"], ["Slow and graceful", "slow, graceful movement"], ["Natural", "natural, realistic movement"], ["Energetic", "fast, energetic movement"]]],
  ["Pacing", "Motion", MOV, [["Calm", "calm, unhurried pacing"], ["Dynamic", "dynamic pacing"], ["Slow motion", "in slow motion"], ["Time-lapse", "as a time-lapse"], ["One take", "one continuous take"]]],
  ["Ambience", "Sound", MOV, [["Quiet room", "the quiet hum of a room"], ["City street", "busy city traffic and distant voices"], ["Café", "a busy café with chatter and clinking cups"], ["Nature", "birdsong and leaves rustling in the wind"], ["Rain", "steady rain"], ["Ocean", "waves rolling onto the shore"], ["Crowd", "a cheering crowd"], ["Night", "crickets and a soft night breeze"]]],
  ["Music", "Sound", MOV, [["Soft piano", "a soft piano score"], ["Tense strings", "tense, pulsing strings"], ["Epic orchestral", "a swelling orchestral score"], ["Upbeat pop", "an upbeat pop track"], ["Lo-fi", "a mellow lo-fi beat"], ["Synthwave", "retro synthwave"]]],
  ["Genre", "Music", ["music"], [["Pop", "pop"], ["Hip hop", "hip hop"], ["Lo-fi", "lo-fi hip hop"], ["Electronic", "electronic dance"], ["House", "deep house"], ["Techno", "dark techno"], ["Rock", "rock"], ["Indie", "indie"], ["Acoustic folk", "acoustic folk"], ["R&B", "R&B"], ["Jazz", "jazz"], ["Classical", "classical"], ["Cinematic", "cinematic orchestral"], ["Ambient", "ambient"], ["Synthwave", "synthwave"], ["Country", "country"], ["Reggaeton", "reggaeton"], ["Afrobeats", "afrobeats"]]],
  ["Feel", "Music", ["music"], [["Happy", "happy"], ["Uplifting", "uplifting"], ["Chill", "chilled"], ["Romantic", "romantic"], ["Sad", "melancholic"], ["Dark", "dark"], ["Tense", "tense"], ["Epic", "epic"], ["Dreamy", "dreamy"], ["Playful", "playful"]]],
  ["Instruments", "Music", ["music"], [["Piano", "piano"], ["Acoustic guitar", "acoustic guitar"], ["Electric guitar", "electric guitar"], ["Strings", "strings"], ["Synths", "synthesizers"], ["808 bass", "808 bass"], ["Drums", "live drums"], ["Brass", "brass"], ["Choir", "choir"]], true],
  ["Tempo", "Music", ["music"], [["Slow", "a slow tempo around 70 BPM"], ["Medium", "a mid tempo around 100 BPM"], ["Fast", "a fast tempo around 128 BPM"]]],
  ["Vocals", "Music", ["music"], [["Instrumental", "instrumental, no vocals"], ["Female vocals", "female vocals"], ["Male vocals", "male vocals"], ["Duet", "a male and female duet"], ["Rap", "rap vocals"]]],
  ["Production", "Music", ["music"], [["Polished", "polished, radio-ready production"], ["Raw and live", "a raw, live-band recording"], ["Vintage", "warm vintage production with tape saturation"], ["Lo-fi", "lo-fi production with vinyl crackle"]]],
  ["Place", "Sound", ["sfx"], [["Close", "recorded close up"], ["Distant", "heard from a distance"], ["Small room", "in a small room"], ["Big hall", "in a large echoing hall"], ["Outdoors", "outdoors in the open"], ["Underwater", "muffled, underwater"]]],
  ["Texture", "Sound", ["sfx"], [["Crisp", "crisp and clear"], ["Deep", "deep and booming"], ["Metallic", "metallic"], ["Soft", "soft and gentle"], ["Gritty", "gritty and distorted"]]],
];
// one click sets several choices at once
const PLOOKS = [
  ["Cinematic film still", VIS, { Medium: ["Cinematic still"], Camera: ["Cinema camera"], "Lens character": ["Anamorphic"], "Colour grade": ["Teal & orange"], Grain: ["Fine"] }],
  ["Natural phone photo", VIS, { Medium: ["Photo"], Camera: ["Phone"], Lighting: ["Soft window"], "Colour grade": ["Natural"], Grain: ["None"] }],
  ["Studio product shot", VIS, { Medium: ["Product shot"], Lighting: ["Studio softbox"], Aperture: ["f/8"], Composition: ["Centred"], "Colour grade": ["Natural"] }],
  ["Editorial fashion", VIS, { Medium: ["Photo"], Camera: ["Medium format"], "Film stock": ["Portra 400"], Lighting: ["Flash"], Composition: ["Negative space"] }],
  ["Golden-hour portrait", VIS, { Medium: ["Photo"], "Shot size": ["Close-up"], "Focal length": ["85mm"], Aperture: ["f/1.4"], Lighting: ["Golden hour"] }],
  ["90s snapshot", VIS, { Medium: ["Photo"], Era: ["1990s"], Camera: ["Disposable"], Lighting: ["Flash"], Grain: ["Heavy"] }],
  ["Moody night", VIS, { Medium: ["Cinematic still"], "Film stock": ["CineStill 800T"], Lighting: ["Neon"], "Time and weather": ["Rain"], Mood: ["Mysterious"] }],
  ["Film noir", VIS, { Medium: ["Cinematic still"], Era: ["Black & white"], Lighting: ["Rembrandt"], Mood: ["Mysterious"], "Camera angle": ["Low angle"] }],
  ["Anime key visual", VIS, { Medium: ["Anime"], Lighting: ["Backlit"], "Colour grade": ["Vivid"], Mood: ["Epic"] }],
  ["3D animated film", VIS, { Medium: ["3D animation"], Lighting: ["Soft window"], "Colour grade": ["Vivid"], Mood: ["Joyful"] }],
  ["Documentary", VIS, { Medium: ["Documentary"], "Focal length": ["35mm"], Lighting: ["Overcast"], "Colour grade": ["Muted"], "Camera move": ["Handheld"] }],
  ["Luxury advert", VIS, { Medium: ["Product shot"], Lighting: ["Backlit"], Aperture: ["f/2.8"], "Colour grade": ["Moody"], "Camera move": ["Slow push in"], Pacing: ["Slow motion"] }],
  ["Epic landscape", VIS, { Medium: ["Photo"], "Shot size": ["Establishing"], "Camera angle": ["Aerial"], Aperture: ["f/16"], Lighting: ["Golden hour"], "Camera move": ["Drone"] }],
  ["Lo-fi study beat", ["music"], { Genre: ["Lo-fi"], Feel: ["Chill"], Instruments: ["Piano", "Drums"], Tempo: ["Slow"], Vocals: ["Instrumental"], Production: ["Lo-fi"] }],
  ["Epic trailer", ["music"], { Genre: ["Cinematic"], Feel: ["Epic"], Instruments: ["Strings", "Brass", "Choir"], Tempo: ["Medium"], Vocals: ["Instrumental"], Production: ["Polished"] }],
  ["Feel-good pop", ["music"], { Genre: ["Pop"], Feel: ["Happy"], Instruments: ["Synths", "Drums"], Tempo: ["Fast"], Vocals: ["Female vocals"], Production: ["Polished"] }],
  ["Acoustic and warm", ["music"], { Genre: ["Acoustic folk"], Feel: ["Romantic"], Instruments: ["Acoustic guitar", "Piano"], Tempo: ["Slow"], Vocals: ["Male vocals"], Production: ["Raw and live"] }],
];
const TABS = { image: ["Looks", "Style", "Shot", "Camera", "Light", "Colour"], edit: ["Looks", "Style", "Camera", "Light", "Colour"],
  video: ["Looks", "Style", "Shot", "Camera", "Light", "Colour", "Motion", "Sound"], i2v: ["Looks", "Motion", "Style", "Light", "Colour", "Sound"],
  music: ["Looks", "Music"], sfx: ["Sound"] };
const groupsFor = (mode, tab) => BUILD.filter(([, t, modes]) => t === tab && modes.includes(mode));
// the lines the builder adds to the end of a prompt; it rewrites only these, never what the person typed
const BLOCK = /(?:\n*(?:Look|Cinematography|Camera move|Motion|Ambient noise|SFX|Music|Dialogue|Style): [^\n]*)+\s*$/;
function buildLines(sel, mode) {
  const w = g => (sel[g] || []).map(l => BUILD.find(b => b[0] === g)?.[3].find(o => o[0] === l)?.[1]).filter(Boolean), one = g => w(g)[0];
  const cap = x => x && x[0].toUpperCase() + x.slice(1);
  if (mode === "music") {
    const bits = [[one("Feel"), one("Genre")].filter(Boolean).join(" "), w("Instruments").length && "with " + w("Instruments").join(", "), one("Tempo") && "at " + one("Tempo"), one("Vocals"), one("Production")].filter(Boolean);
    return bits.length ? [`Style: ${cap(bits.join(", "))}.`] : [];
  }
  if (mode === "sfx") { const b = [one("Place"), one("Texture")].filter(Boolean); return b.length ? [`Style: ${cap(b.join(", "))}.`] : []; }
  const shot = [one("Shot size"), one("Camera angle")].filter(Boolean).join(" ");
  const kit = [one("Focal length"), one("Aperture")].filter(Boolean);
  const cam = one("Camera") ? one("Camera") + (kit.length ? ", " + kit.join(" at ") : "") : kit.length ? "shot with " + kit.join(" at ") : "";
  const look = [one("Medium"), shot, one("Composition"), cam, one("Lens character"), one("Shutter"), one("Film stock"), one("Grain"), one("Lighting"), one("Time and weather"), one("Era"), one("Colour grade"), one("Mood")]
    .filter(Boolean).map(cap);
  const out = look.length ? [`${MOV.includes(mode) ? "Cinematography" : "Look"}: ${look.join(". ")}.`] : [];
  if (MOV.includes(mode)) {
    const moves = w("Camera move");
    if (moves.length) out.push(`Camera move: ${cap(moves.join(", then "))}.`);
    const mo = [one("Subject motion"), one("Pacing")].filter(Boolean);
    if (mo.length) out.push(`Motion: ${cap(mo.join(", "))}.`);
    if (one("Ambience")) out.push(`Ambient noise: ${cap(one("Ambience"))}.`);
    if (sel.sfx) out.push(`SFX: ${cap(sel.sfx.replace(/\.$/, ""))}.`);
    if (one("Music")) out.push(`Music: ${cap(one("Music"))}.`);
    if (sel.line) out.push(`Dialogue: ${sel.who || "The character"} says, "${sel.line.replace(/^"|"$/g, "")}"`);
  }
  return out;
}

// the live checklist: what a strong prompt for this kind of model has, and what this one is missing
const HAS = {
  Subject: t => t.split(/\s+/).filter(Boolean).length >= 3,
  Action: t => /\b\w+ing\b|\b(sits?|stands?|walks?|runs?|holds?|looks?|smiles?|jumps?|dances?|leans?|poses?|lies|turns?|reaches?|drinks?|eats?|reads?|plays?|flies|floats?|rests?)\b/i.test(t),
  Setting: t => /\b(in|on|at|inside|outside|against|under|beneath|beside|near|across|through|above|over)\s+(a|an|the|his|her|their|my|\w+)\b/i.test(t),
  Lighting: t => /\b(light|lit|lighting|sun|sunlight|sunset|sunrise|golden hour|shadow|glow|neon|candle|backlit|softbox|overcast|moon|flash|dusk|dawn|night)\w*/i.test(t),
  Style: t => /\b(photo|photograph|cinematic|film|anime|illustration|painting|render|3d|watercolou?r|realistic|style|aesthetic|editorial|documentary|claymation|pixel|comic|vintage|retro)\w*/i.test(t),
  Camera: t => /\b(shot|close-?up|angle|lens|\d{2,3}\s?mm|f\/\d|aperture|depth of field|bokeh|wide|overhead|aerial|portrait|macro|profile|framing|composition)\b/i.test(t),
  "Camera move": t => /\b(push(es)? in|pull(s)? (back|out)|pan|tilt|track|follow|orbit|circl|dolly|crane|zoom|handheld|still camera|static|locked-off|drone|gimbal|rises?)\w*/i.test(t),
  Movement: t => /\b\w+(s|ing)\b/.test(t) && /\b(mov|turn|walk|run|danc|wav|blink|smil|laugh|fall|flow|blow|sway|ris|spin|jump|look|reach|open|clos|drift|swirl|ripple|flicker|nod|speak|says?)\w*/i.test(t),
  Change: t => /^\s*(change|make|replace|remove|add|turn|put|swap|transform|give|recolou?r|restyle|place|erase|edit|convert|keep)\b/i.test(t),
  "What stays": t => /\b(keep|same|unchanged|preserv|identical|don't change|do not change|exactly as)\w*/i.test(t),
  Genre: t => /\b(pop|rock|jazz|hip ?hop|lo-?fi|house|techno|electronic|classical|orchestral|folk|ambient|synth|r&b|country|metal|reggae|trap|edm|indie|soul|funk|blues|cinematic)\b/i.test(t),
  Mood: t => /\b(happy|sad|chill|dark|epic|uplifting|calm|romantic|melanchol|tense|dreamy|energetic|playful|moody|warm|nostalgic)\w*/i.test(t),
  Instruments: t => /\b(piano|guitar|strings|synth|bass|drums?|brass|choir|violin|cello|saxophone|flute|808|vocals?)\w*/i.test(t),
  Tempo: t => /\b(\d{2,3}\s?bpm|tempo|slow|fast|upbeat|mid-?tempo|driving)\b/i.test(t),
  Source: t => t.split(/\s+/).filter(Boolean).length >= 2,
  Space: t => /\b(room|hall|outdoor|outside|inside|street|forest|cave|underwater|distance|close|far|echo|reverb)\w*/i.test(t),
};
const CHECKS = { image: ["Subject", "Action", "Setting", "Lighting", "Style", "Camera"], edit: ["Change", "What stays", "Lighting", "Style"],
  video: ["Subject", "Action", "Setting", "Camera move", "Lighting", "Style"], i2v: ["Movement", "Camera move", "Lighting", "Style"],
  music: ["Genre", "Mood", "Instruments", "Tempo"], sfx: ["Source", "Space"] };
const CHECK_TAB = { Lighting: "Light", Style: "Style", Camera: "Camera", "Camera move": "Motion", Movement: "Motion", Genre: "Music", Mood: "Music", Instruments: "Music", Tempo: "Music", Space: "Sound" };
const CHECK_TIP = { Subject: "Say who or what it's of, with a detail or two (age, clothes, materials, colours)", Action: "Say what they're doing", Setting: "Say where it is", Change: "Start with what to change: “Change…”, “Replace…”, “Add…”", "What stays": "Say what must stay the same, e.g. “Keep her face and the background exactly the same”", Source: "Say what makes the sound and what it's doing" };
function promptTips(t, mode, hasNegBox) {
  const tips = [], words = t.split(/\s+/).filter(Boolean).length, body = t.replace(BLOCK, "");
  if (words && words < 6 && mode !== "sfx") tips.push("Add a little more: who or what, doing what, and where.");
  if (/\b(no|without|don'?t|do not|never|avoid)\s+(\w+)/i.test(body) && VIS.includes(mode)) tips.push(`Describe what you want rather than what you don't (e.g. “an empty street”, not “no cars”)${hasNegBox ? ", or put it in Negative prompt" : ""}.`);
  if ((body.match(/,/g) || []).length >= 7 && !/\b(is|are|with|while|as)\b/i.test(body)) tips.push("Write it as a sentence or two: these models follow descriptions better than lists of keywords.");
  if (MOV.includes(mode) && (body.match(/\bthen\b/gi) || []).length >= 2) tips.push("One clear action per clip works best; make the rest a separate clip.");
  if (mode === "i2v" && words > 70) tips.push("The picture already shows the scene: describe what moves and how, not what's in it.");
  if (/\b(text|sign|title|caption|logo|headline|words?|says)\b/i.test(body) && !/["“”]/.test(body) && VIS.includes(mode)) tips.push("Put any words that should appear in “quotes”, and say the font style.");
  return tips;
}
function coach(ta, mode, box) {
  const t = ta.value, checks = CHECKS[mode] || [], hit = checks.filter(c => HAS[c](t));
  const level = !t.trim() ? "" : hit.length >= checks.length ? "Strong" : hit.length >= checks.length - 2 ? "Good" : "Basic";
  const tips = t.trim() ? promptTips(t, mode, !!ta.closest(".form")?.querySelector('[data-k*="negative"]')) : [];
  box.innerHTML = `<span class="plevel ${level.toLowerCase()}">${level ? level + " prompt" : "A strong prompt covers:"}</span>`
    + checks.map(c => `<button type="button" class="pcheck ${hit.includes(c) ? "on" : ""}" data-c="${esc(c)}" title="${esc(HAS[c](t) ? "Covered" : CHECK_TIP[c] || "Add it with the prompt builder")}">${hit.includes(c) ? "✓" : "○"} ${esc(c)}</button>`).join("")
    + (tips.length ? `<span class="ptip">${esc(tips[0])}</span>` : "");
}

const PSEL = {};  // builder choices per prompt box, kept while the box's settings are redrawn
function promptHelp(ta, getModel, key = "prompt") {
  const mode = () => promptMode(getModel(), key);
  if (!mode()) return;
  const bar = document.createElement("div"); bar.className = "ptools";
  bar.innerHTML = `${TABS[mode()] ? `<button type="button" class="btn small ghost" data-pt="build" title="Pick the look, shot, camera, light${MOV.includes(mode()) ? ", camera moves and sound" : ""} in plain words">🎬 Prompt builder</button>` : ""}<button type="button" class="btn small ghost" data-pt="improve" title="The assistant rewrites it the way an expert would, following the model maker's own guide (about a tenth of a cent)">✦ Improve my prompt</button>`;
  const box = document.createElement("div"); box.className = "pcoach";
  ta.after(bar, box);
  const sid = () => (getModel()?.id || "any") + ":" + key + ":" + (ta.id || "");
  const redraw = () => coach(ta, mode(), box);
  ta.addEventListener("input", e => { redraw(); if (e.isTrusted && ta._undo != null) { ta._undo = null; bar.querySelector('[data-pt="improve"]').textContent = "✦ Improve my prompt"; } });
  redraw();
  box.onclick = e => { const c = e.target.closest(".pcheck:not(.on)")?.dataset.c; if (!c) return; if (CHECK_TAB[c] && TABS[mode()]?.includes(CHECK_TAB[c])) openBuilder(ta, bar, mode(), sid(), CHECK_TAB[c], getModel()); else { toast(CHECK_TIP[c] || "Add it to your prompt.", 6000); ta.focus(); } };
  bar.onclick = async e => {
    const b = e.target.closest("[data-pt]"); if (!b) return;
    if (b.dataset.pt === "build") return openBuilder(ta, bar, mode(), sid(), null, getModel());
    if (ta._undo != null) { ta.value = ta._undo; ta._undo = null; b.textContent = "✦ Improve my prompt"; return ta.dispatchEvent(new Event("input", { bubbles: true })); }
    improvePrompt(ta, getModel(), mode(), b);
  };
}
const IMPROVE = {
  image: "Write it as one to three natural sentences, never a keyword list. Start with the main subject (with specific details: age, clothing, materials, textures, colours) and what it is doing, then the setting, then composition and camera angle, then the lighting, then the style or medium and, where it helps, camera details (lens, aperture, film stock). Describe what should be there, never “no X”. Put any words that must appear in the image in quotes and say their font style.",
  edit: "It is an edit of the attached image(s). Start with a clear verb saying exactly what to change, be specific about the new thing (materials, colours, position), then say what must stay exactly the same (faces, pose, framing, background, lighting, product labels). Don't describe the whole picture again.",
  video: "Use this order: the shot and camera, the subject (with specific details), one clear main action for a short clip, the setting, then lighting, style and mood. Put the camera movement in its own sentence. Describe what should be there, never “no X”.",
  i2v: "The starting picture already shows the subject and the scene, so don't describe them again. Describe what moves and how (the subject's movement first, with concrete verbs and speed), then the camera movement in its own sentence, then the pacing. One clear action for a short clip.",
  music: "Describe the track in one or two sentences: genre, mood, main instruments, tempo (with a BPM), vocals or instrumental, and production style.",
  sfx: "Describe the sound in one sentence: what makes it, what it's doing, the space it's in (small room, large hall, outdoors), how far away, and its texture.",
};
async function improvePrompt(ta, m, mode, b) {
  if (!ta.value.trim()) return toast("Write a rough idea first, even a few words.");
  b.disabled = true; b.textContent = "Improving…";
  try {
    const better = (await write(`You are an expert prompt writer for AI ${mode === "music" ? "music" : mode === "sfx" ? "sound-effect" : MOV.includes(mode) ? "video" : "image"} models. Rewrite the person's idea into one excellent prompt for ${m ? `${m.name} (${m.cat})` : "this model"}. ${IMPROVE[mode] || IMPROVE.image}
Keep their intent, their language, every @Name exactly as written, and any quoted text. Fold any “Look:” or “Cinematography:” line into the prompt naturally; keep “Camera move:”, “Ambient noise:”, “SFX:”, “Music:” and “Dialogue:” lines as separate lines at the end. Reply with only the prompt: no title, no quotes around it, no commentary.`, ta.value)).trim();
    if (better) { ta._undo = ta.value; ta.value = better; ta.dispatchEvent(new Event("input", { bubbles: true })); }
    b.textContent = ta._undo != null ? "↶ Undo" : "✦ Improve my prompt";
  } catch (err) { toast(err.message, 6000); b.textContent = "✦ Improve my prompt"; }
  b.disabled = false;
}
// prompt help in every model's settings
function promptTools(form) {
  form.querySelectorAll('textarea[data-k]:not([data-lines])').forEach(ta => {
    if (!/prompt|^text$/.test(ta.dataset.k) || /negative/.test(ta.dataset.k)) return;
    promptHelp(ta, () => byId(form.dataset.model), ta.dataset.k);
  });
}
function openBuilder(ta, anchor, mode, sid, tab, m) {
  const p = $("#direct");
  if (!BLOCK.test(ta.value)) delete PSEL[sid];  // the person deleted the added lines: start again
  const sel = PSEL[sid] ||= {}, tabs = TABS[mode];
  let cur = tab || p._tab?.[mode] || tabs[0];
  const apply = () => {
    const lines = buildLines(sel, mode), base = ta.value.replace(BLOCK, "").replace(/\s+$/, "");
    ta.value = lines.length ? (base ? base + "\n\n" : "") + lines.join("\n") : base;
    ta.dispatchEvent(new Event("input", { bubbles: true })); draw();
  };
  const chip = (g, l, hint, multi) => { const k = (sel[g] || []).indexOf(l); return `<button type="button" class="${k >= 0 ? "on" : ""}" data-g="${esc(g)}" data-l="${esc(l)}" data-h="${esc(hint || "")}">${multi && k >= 0 ? `${k + 1}. ` : ""}${esc(l)}</button>`; };
  const draw = () => {
    (p._tab ||= {})[mode] = cur;
    const looks = PLOOKS.filter(([, modes]) => modes.includes(mode));
    const body = cur === "Looks"
      ? `<p class="muted small">One click sets the style, camera and light together. You can fine-tune it in the other tabs.</p><div class="chips looks">${looks.map(([l]) => `<button type="button" data-look="${esc(l)}">${esc(l)}</button>`).join("")}</div>`
      : groupsFor(mode, cur).map(([g, , , opts, multi]) => `<h5>${esc(g)}${multi ? " <span>(pick in order)</span>" : ""}</h5><div class="chips">${opts.map(([l, , h]) => chip(g, l, h, multi)).join("")}</div>`).join("")
        + (cur === "Sound" && MOV.includes(mode) ? `<h5>Sound effect</h5><input data-f="sfx" placeholder="e.g. a door slams shut" value="${esc(sel.sfx || "")}">
          <h5>Dialogue <span>(for video models that make sound)</span></h5><div class="row"><input data-f="who" placeholder="Who, e.g. The woman" value="${esc(sel.who || "")}" style="flex: 0 0 34%"><input data-f="line" placeholder="What they say" value="${esc(sel.line || "")}"></div>` : "");
    p.innerHTML = `<div class="bhead"><b>🎬 Prompt builder</b><span class="grow"></span><button class="btn small ghost" data-clear>Clear</button><button class="btn small ghost" data-x>Done</button></div>
      <div class="btabs">${tabs.map(t => `<button type="button" class="${t === cur ? "on" : ""}" data-tab="${esc(t)}">${esc(t)}</button>`).join("")}</div>
      <div class="bbody">${body}</div>
      <p class="bhint" id="bHint">${mode === "i2v" ? "Your picture already shows the scene: focus on how things move." : "Hover over an option to see what it does."}</p>
      <div class="bfoot"><span class="muted small grow">${esc(buildLines(sel, mode).join(" ") || "Nothing picked yet.")}</span>${buildLines(sel, mode).length ? `<button class="btn small" data-blend title="The assistant blends your choices into one flowing prompt (about a tenth of a cent)">✦ Blend into one prompt</button>` : ""}</div>`;
    p.querySelector("[data-x]").onclick = () => p.hidden = true;
    p.querySelector("[data-clear]").onclick = () => { for (const k in sel) delete sel[k]; apply(); };
    p.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { cur = b.dataset.tab; draw(); });
    p.querySelectorAll("[data-h]").forEach(b => b.onmouseenter = () => { const o = BUILD.find(x => x[0] === b.dataset.g)[3].find(o => o[0] === b.dataset.l); $("#bHint").textContent = (b.dataset.h ? b.dataset.h + " · " : "") + "adds “" + o[1] + "”"; });
    p.querySelectorAll("[data-look]").forEach(b => b.onclick = () => {
      const set = PLOOKS.find(x => x[0] === b.dataset.look)[2];
      for (const [g, v] of Object.entries(set)) if (BUILD.find(x => x[0] === g)?.[2].includes(mode)) sel[g] = [...v];
      apply();
    });
    p.querySelectorAll("[data-g]").forEach(b => b.onclick = () => {
      const g = b.dataset.g, l = b.dataset.l, multi = BUILD.find(d => d[0] === g)[4], have = sel[g] || [];
      sel[g] = have.includes(l) ? have.filter(x => x !== l) : multi ? [...have, l] : [l];
      if (!sel[g].length) delete sel[g];
      apply();
    });
    p.querySelectorAll("[data-f]").forEach(i => i.onchange = () => { sel[i.dataset.f] = i.value.trim(); if (!sel[i.dataset.f]) delete sel[i.dataset.f]; apply(); });
    const blend = p.querySelector("[data-blend]");
    if (blend) blend.onclick = async () => { p.hidden = true; await improvePrompt(ta, m, mode, anchor.querySelector('[data-pt="improve"]')); delete PSEL[sid]; };
    place();
  };
  function place() {  // below the button, but always on screen
    const r = anchor.getBoundingClientRect(), top = Math.max(8, Math.min(r.bottom + 6, innerHeight - p.offsetHeight - 8));
    Object.assign(p.style, { left: Math.max(8, Math.min(innerWidth - p.offsetWidth - 8, r.left + scrollX)) + "px", top: top + scrollY + "px" });
  }
  p.hidden = false; draw();
}
document.addEventListener("mousedown", e => { if (!e.target.closest("#direct, .ptools, .pcoach")) $("#direct").hidden = true; });

// ---------- Apps: one-click tools for any picture or video ----------
const APPS = [
  { label: "Upscale", desc: "Sharper and bigger", image: "fal-ai/seedvr/upscale/image", video: "topaz/upscale/video/precision" },
  { label: "Remove background", desc: "Cut out the subject", image: "fal-ai/bria/background/remove", video: "veed/video-background-removal/fast" },
  { label: "Animate", desc: "Turn the picture into a video", image: "animate" },
  { label: "Edit an area", desc: "Paint over a part and say what goes there", image: "brush" },
  { label: "Expand the frame", desc: "See more around it", image: "fal-ai/flux-2-pro/outpaint" },
  { label: "Relight", desc: "New lighting, same scene", image: "fal-ai/image-apps-v2/relighting" },
  { label: "New camera angle", desc: "The same scene from elsewhere", image: "fal-ai/qwen-image-edit-2511-multiple-angles" },
  { label: "9 camera angles", desc: "A contact sheet of views", image: "angles" },
  { label: "Effects", desc: "150+ one-click video effects", image: "fal-ai/pixverse/v5.5/effects" },
  { label: "Virtual try-on", desc: "Put an outfit on a person", image: "fal-ai/image-apps-v2/virtual-try-on" },
  { label: "Recreate", desc: "Same shot, your character or product", image: "recreate", video: "recreate" },
  { label: "Scroll-stop score", desc: "Would it stop the scroll?", image: "score", video: "score" },
  { label: "Extend the video", desc: "Carry on from the last frame", video: "minimax/h3-max-turbo/extend-video" },
  { label: "Motion transfer", desc: "Copy this motion onto someone else", video: "fal-ai/wan/v2.2-14b/animate/move" },
  { label: "Object swap", desc: "Keep the shot, replace one thing", video: "fal-ai/kling-video/o3/standard/video-to-video/edit" },
  { label: "Lip sync", desc: "Make the face say something", video: "lipsync" },
  { label: "Add to the Editor", desc: "Put it on the timeline", video: "timeline" },
  { label: "Use as a Film keyframe", desc: "Start a scene from it", image: "story" },
];
const SPECIAL = ["animate", "brush", "angles", "recreate", "score", "lipsync", "timeline", "story"];
const appsFor = u => { const k = mediaOf(u); return APPS.filter(a => a[k] && (SPECIAL.includes(a[k]) || byId(a[k]))); };
async function useApp(a, u, box) {
  const k = mediaOf(u), target = a[k];
  if (target === "faceswap") return faceSwap(u);
  if (target === "editor") {  // a prompt written for the picture editor, with [brackets] to fill in
    const id = EDITOR(); if (!id) return toast("This app isn't available right now.");
    go("image"); await C.pick(byId(id), fillFor(await schemaOf(id), { prompt: a.prompt, images: [u] }));
    return toast(/\[/.test(a.prompt) ? "Replace the part in [brackets], then press Run." + (/second image/.test(a.prompt) ? " Add your product's picture as a second image." : "") : "Ready: press Run.", 7000);
  }
  if (/ai-avatar/.test(target)) setTimeout(() => toast("Add the voice for it to say (make one in Audio › Voice), then press Run.", 7000), 1500);
  if (target === "score") return scoreIt(u, box || $("#appOut"));
  if (target === "brush") { EDIT.url = u; return go("edit"); }
  if (target === "timeline") { TL.clips.push({ url: u }); saveTL(); return toast(`Added to the Editor (clip ${TL.clips.length}).`); }
  if (target === "story") { STORY.scenes.push({ id: Date.now().toString(36), prompt: "", motion: "", key: u }); saveSB(); return go("storyboard"); }
  if (target === "angles") return nineAngles(u);
  if (target === "recreate") return recreate(u);
  if (target === "lipsync") { go("lipsync"); await AU.ready; Object.assign(AU.values, fillFor(AU.schema, { videos: [u] })); AU.redraw(); return toast("Now add the voice or song for it to say."); }
  const id = target === "animate" ? (store.get("ml_model_video_i2v") || ["fal-ai/kling-video/v3/standard/image-to-video"].find(byId) || MODELS.find(m => /image-to-video/.test(m.cat))?.id) : target;
  go(target === "animate" ? "video" : "simple");
  const s = await schemaOf(id);
  await C.pick(byId(id), fillFor(s, k === "video" ? { videos: [u] } : { images: [u] }));
  if (/video-to-video\/edit/.test(id)) { const pk = promptKey(s); if (pk) { C.values[pk] = "Replace [the thing in the video] with [what you want]. Keep everything else in the shot exactly the same."; C.redraw(); } }
  toast(`${a.label}: check the settings, then press Run.`, 5000);
}
const ANGLES = ["front view at eye level", "three-quarter view from the left", "three-quarter view from the right", "side profile from the left", "low angle looking up", "high angle looking down", "from directly overhead", "from behind", "extreme close-up on the face"];
async function nineAngles(u) {
  const id = ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"].find(byId); if (!id) return toast("This app isn't available right now.");
  const s = await schemaOf(id), q = await quote(id, fillFor(s, { prompt: "x", images: [u] })).catch(() => null);
  if (!(await dialog("9 camera angles", `<p class="muted">Nine runs of ${esc(byId(id).name)}, one per camera angle, keeping everything else the same${q ? `: about ${money(q.price * 9)} in all` : ""}.</p>`, "Make 9 angles"))) return;
  ANGLES.forEach((a, i) => launch(id, fillFor(s, { prompt: `The same scene, subject, outfit and lighting as the reference image, re-photographed ${a}. Keep every detail identical; only the camera position changes.`, images: [u] }), `Angle ${i + 1} of 9`).catch(e => toast(e.message)));
  toast("Nine angles started. They appear under Latest.");
}
async function recreate(u) {
  const els = ACC.library.filter(li => li.files?.length);
  if (!els.length) return toast("Add a character or product with pictures to the Library first.");
  const d = await dialog("Recreate", `<p class="muted">Keeps this ${isVideo(u) ? "video's" : "picture's"} composition, camera, lighting and style, and puts your own subject in it.</p>
    <label class="field">Swap in<select id="rcEl">${els.map(li => `<option>${esc(li.name)}</option>`).join("")}</select></label>
    <label class="field">Anything else to change<span class="hint">Optional</span><input id="rcNote" placeholder="e.g. make it night time"></label>`, "Set it up");
  if (!d) return;
  const li = els.find(x => x.name === d.querySelector("#rcEl").value), note = d.querySelector("#rcNote").value.trim(), video = isVideo(u);
  const id = video ? "fal-ai/kling-video/o3/standard/video-to-video/edit" : ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"].find(byId);
  if (!byId(id)) return toast("This app isn't available right now.");
  const s = await schemaOf(id);
  go(video ? "video" : "image");
  await C.pick(byId(id), fillFor(s, { prompt: `Recreate the reference ${video ? "video" : "image"} exactly: same composition, framing, camera angle, pose, lighting, colours and style. Replace its main subject with @${libTag(li.name)}.${note ? " " + note : ""}`, [video ? "videos" : "images"]: [u] }));
  toast("Recreate is set up. Check it, then press Run.", 5000);
}
// a grid of your recent pictures or videos, plus an upload button
function mediaPicker(box, test, onPick, current) {
  const items = outputs(test).slice(0, 40);
  box.innerHTML = `<div class="pickgrid"><button type="button" class="up">＋ Upload</button>${items.map(u => `<button type="button" class="${u === current ? "on" : ""}" data-u="${esc(u)}">${isVideo(u) ? `<video src="${esc(u)}#t=0.1" muted preload="metadata" playsinline></video>` : `<img src="${esc(u)}" alt="" loading="lazy">`}</button>`).join("")}
    </div><input type="file" hidden>`;
  box.querySelectorAll("[data-u] img, [data-u] video").forEach(m => m.onerror = () => m.parentNode.remove());  // files that have expired
  const input = box.querySelector("input");
  input.accept = test === isVideo ? "video/*" : test === isAudio ? "audio/*" : "image/*,video/*";
  box.querySelector(".up").onclick = () => input.click();
  input.onchange = async () => { const f = input.files[0]; if (!f) return; try { onPick(await upload(f)); } catch (e) { toast(e.message); } };
  box.querySelectorAll("[data-u]").forEach(b => b.onclick = () => onPick(b.dataset.u));
}
// every tool is on show straight away; choosing one then asks for the picture or video to use it on
function drawApps() {
  const ok = (a, k) => a[k] && (SPECIAL.includes(a[k]) || byId(a[k]));
  $("#appList").innerHTML = [["image", "For pictures"], ["video", "For videos"]].map(([k, title]) => `<h3 class="subhead">${title}</h3>
    <div class="apps">${APPS.filter(a => ok(a, k)).map(a => `<button type="button" class="appcard" data-i="${APPS.indexOf(a)}" data-k="${k}"><b>${esc(a.label)}</b><span>${esc(a.desc)}</span></button>`).join("")}</div>`).join("");
  $("#appList").querySelectorAll("[data-i]").forEach(b => b.onclick = async () => {
    const a = APPS[+b.dataset.i], u = await pickMedia(b.dataset.k, a.label);
    if (u) useApp(a, u, $("#appOut"));
  });
}
function pickMedia(k, title) {
  return new Promise(done => {
    const d = document.createElement("div"); d.className = "dlg";
    d.innerHTML = `<div class="box wide"><h2>${esc(title)}</h2><p class="muted">Choose one of your ${k === "video" ? "videos" : "pictures"}, or upload one.</p><div></div><div class="row"><span class="grow"></span><button class="btn" data-x>Cancel</button></div></div>`;
    document.body.append(d);
    const close = u => { d.remove(); done(u); };
    mediaPicker(d.querySelector(".box > div"), k === "video" ? isVideo : u => !isVideo(u) && !isAudio(u), close);
    d.querySelector("input[type=file]").accept = k + "/*";
    d.querySelector("[data-x]").onclick = () => close(null);
    d.onclick = e => { if (e.target === d) close(null); };
  });
}

// prompt help on the prompt boxes that aren't part of a model's settings
promptHelp($("#cmpPrompt"), () => byId(CMP[0]));
promptHelp($("#skPrompt"), () => null);
promptHelp($("#edPrompt"), () => ({ id: "edit", cat: "image-to-image", name: "the picture editor" }));

// ---------- Images › Edit: say what to change, or paint over the part to change ----------
const EDIT = { url: "", painted: false };
function drawEdit() {
  mediaPicker($("#edPick"), u => !isVideo(u) && !isAudio(u), u => { EDIT.url = u; drawEdit(); }, EDIT.url);
  $("#edStage").hidden = !EDIT.url;
  if (!EDIT.url) return;
  const img = $("#edImg"), cv = $("#edCv");
  if (img.dataset.u !== EDIT.url) {
    img.dataset.u = EDIT.url; img.crossOrigin = "anonymous";
    img.onload = () => { cv.width = img.naturalWidth; cv.height = img.naturalHeight; cv.getContext("2d").clearRect(0, 0, cv.width, cv.height); EDIT.painted = false; edPrice(); };
    img.src = EDIT.url;
  }
}
(() => {
  const cv = $("#edCv"); let down = false;
  const at = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
  const dot = e => { const c = cv.getContext("2d"), [x, y] = at(e), r = +$("#edBrush").value * cv.width / cv.getBoundingClientRect().width / 2; c.fillStyle = "#ff3b6b"; c.beginPath(); c.arc(x, y, r, 0, 7); c.fill(); if (!EDIT.painted) { EDIT.painted = true; edPrice(); } };
  cv.onpointerdown = e => { down = true; cv.setPointerCapture(e.pointerId); dot(e); };
  cv.onpointermove = e => { if (down) dot(e); };
  cv.onpointerup = () => down = false;
  $("#edClear").onclick = () => { cv.getContext("2d").clearRect(0, 0, cv.width, cv.height); EDIT.painted = false; edPrice(); };
})();
const edModel = () => EDIT.painted ? ["fal-ai/flux-pro/v1/fill", "fal-ai/flux-lora/inpainting"].find(byId) : ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit", "fal-ai/bytedance/seedream/v4.5/edit"].find(byId);
async function edInput() {
  const id = edModel(), s = await schemaOf(id), prompt = $("#edPrompt").value.trim() || (EDIT.painted ? "remove it, fill naturally with the surrounding background" : "");
  const input = fillFor(s, { prompt, images: [EDIT.url] });
  if (EDIT.painted) {  // the mask the models want: white where to change, black elsewhere
    const cv = $("#edCv"), out = document.createElement("canvas"); out.width = cv.width; out.height = cv.height;
    const o = out.getContext("2d"); o.fillStyle = "#000"; o.fillRect(0, 0, out.width, out.height);
    o.globalCompositeOperation = "lighter"; o.filter = "brightness(0) invert(1)"; o.drawImage(cv, 0, 0);
    input.image_url = EDIT.url;
    input.mask_url = await upload(new File([await new Promise(r => out.toBlob(r, "image/png"))], "mask.png", { type: "image/png" }));
  }
  return [id, input];
}
let edTimer;
function edPrice() {
  clearTimeout(edTimer);
  $("#edHow").textContent = EDIT.painted ? "Only the painted part changes." : "Describe the change; the whole picture is edited. Paint over a part to change only that.";
  edTimer = setTimeout(async () => { try { const id = edModel(), s = await schemaOf(id); const q = await quote(id, fillFor(s, { prompt: "x", images: [EDIT.url] })); $("#edGo").textContent = "Make the edit · " + money(q.price); } catch { $("#edGo").textContent = "Make the edit"; } }, 300);
}
$("#edGo").onclick = async () => {
  if (!EDIT.url) return toast("Pick a picture first.");
  if (!EDIT.painted && !$("#edPrompt").value.trim()) return toast("Say what to change, or paint over the part to change.");
  $("#edGo").disabled = true;
  try { const [id, input] = await edInput(); const run = await launch(id, input, "Edit"); if (run.status === "done") { EDIT.url = run.outputs[0]; drawEdit(); toast("Done. The edited picture is loaded, so you can keep editing."); } else toast(`The edit didn't work${run.error ? ": " + run.error : ""}. You weren't charged.`, 7000); }
  catch (e) { toast(e.message, 7000); }
  $("#edGo").disabled = false;
};

// ---------- Guided: say what you want; the assistant picks the model and writes an expert prompt ----------
const PRESETS = [
  { t: "Product photo", d: "Your product in a clean studio shot", k: "image", m: ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"], needs: "a photo of your product", p: "Premium studio product photograph of the product in the reference image, seamless light backdrop, soft key light with crisp reflections, commercial catalogue quality. Keep the product exactly as it is." },
  { t: "Professional headshot", d: "A polished portrait from a selfie", k: "image", m: ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"], needs: "a clear photo of the face", p: "Professional corporate headshot of the person in the reference image, same face and identity, neutral grey studio backdrop, soft flattering light, sharp focus, smart business clothing." },
  { t: "Cinematic still", d: "A movie-like frame from an idea", k: "image", m: ["fal-ai/nano-banana-2", "fal-ai/flux-2-pro", "fal-ai/flux/dev"], p: "[Your scene], cinematic film still, anamorphic lens, dramatic lighting, rich colour grade, shallow depth of field." },
  { t: "Illustration", d: "Anime, cartoon or painted styles", k: "image", m: ["fal-ai/nano-banana-2", "fal-ai/flux-2-pro", "fal-ai/flux/dev"], p: "[Your subject], detailed anime illustration, clean line art, soft cel shading, vibrant colours." },
  { t: "Logo", d: "A clean, simple logo", k: "image", m: ["fal-ai/ideogram/v3", "fal-ai/recraft/v3/text-to-image", "fal-ai/nano-banana-2"], p: "Minimal flat vector logo for “[Brand name]”, [style or symbol], two colours, centred on a plain white background." },
  { t: "Poster with text", d: "Readable headline and layout", k: "image", m: ["fal-ai/ideogram/v3", "fal-ai/nano-banana-2"], p: "Bold poster design with the headline “[Your headline]” in large, correctly spelled type, [theme], strong layout, print quality." },
  { t: "Bring a photo to life", d: "Subtle, natural motion", k: "video", m: ["fal-ai/kling-video/v3/standard/image-to-video"], needs: "the photo to animate", p: "Subtle natural motion, gentle breathing and blinking, a slow push in. Keep everything else the same." },
  { t: "Video from an idea", d: "A short clip from words", k: "video", m: ["fal-ai/kling-video/v3/standard/text-to-video"], p: "[Your scene], cinematic, smooth camera movement, natural motion." },
  { t: "Video ad from a link", d: "Paste a shop link, get an ad", ads: true },
  { t: "Voice-over", d: "Natural speech from text", k: "audio", go: "voice" },
  { t: "Song", d: "Music in any style", k: "audio", go: "music" },
  { t: "Sound effect", d: "Any sound you can describe", k: "audio", go: "sfx" },
];
const GUIDED = { photos: [], plan: null };
// the models the guide chooses from: well-known, good ones, with their prices
const CURATED = /^(fal-ai\/nano-banana(-2|-pro)?(\/edit)?|fal-ai\/bytedance\/seedream\/v4\.5\/(text-to-image|edit)|fal-ai\/flux-2-pro(\/edit)?|fal-ai\/flux\/(schnell|dev)|fal-ai\/ideogram\/v3|fal-ai\/recraft\/v3\/text-to-image|fal-ai\/imagen4\/preview(\/fast)?|fal-ai\/qwen-image(-edit)?|fal-ai\/kling-video\/v3\/(standard|pro)\/(text|image)-to-video|fal-ai\/veo3\.1(\/fast)?(\/image-to-video)?|fal-ai\/bytedance\/seedance\/v1(\.5)?\/pro\/(text|image)-to-video|fal-ai\/minimax\/hailuo-02\/standard\/(text|image)-to-video|fal-ai\/sora-2\/(text|image)-to-video|fal-ai\/elevenlabs\/(tts\/eleven-v3|music|sound-effects\/v2)|fal-ai\/sync-lipsync\/v2|fal-ai\/minimax-music\/v2)$/;
function drawGuided() {
  $("#gdPhotos").querySelectorAll(".thumb").forEach(t => t.remove());
  $("#gdPhotoAdd").insertAdjacentHTML("beforebegin", GUIDED.photos.map(thumbHtml).join(""));
  $("#gdPhotos").querySelectorAll(".thumb button").forEach(b => b.onclick = () => { GUIDED.photos = GUIDED.photos.filter(u => u !== b.parentNode.dataset.u); drawGuided(); });
  $("#gdPresets").innerHTML = PRESETS.map((p, i) => { const m = (p.m || []).map(byId).find(Boolean); return `<button type="button" class="preset" data-i="${i}">${m?.thumb ? `<img src="${esc(m.thumb)}" alt="" loading="lazy">` : `<span class="noimg">${p.ads ? "🛍" : p.k === "audio" ? "♪" : "✦"}</span>`}<b>${esc(p.t)}</b><span>${esc(p.d)}</span></button>`; }).join("");
  drawPlan();
}
$("#gdPhotoAdd").onclick = () => $("#gdFile").click();
$("#gdFile").onchange = async () => { for (const f of $("#gdFile").files) { if (GUIDED.photos.length >= 4) break; try { GUIDED.photos.push(await upload(f)); } catch (e) { toast(e.message); } } $("#gdFile").value = ""; drawGuided(); };
$("#gdPresets").onclick = async e => {
  const b = e.target.closest("[data-i]"); if (!b) return;
  const p = PRESETS[+b.dataset.i];
  if (p.ads) { go("marketing"); return $("#mkUrl").focus(); }
  if (p.go) return go(p.go);
  const id = p.m.find(byId); if (!id) return toast("That preset isn't available right now.");
  const s = await schemaOf(id);
  go(p.k === "video" ? "video" : "image");
  await C.pick(byId(id), fillFor(s, { prompt: p.p, images: GUIDED.photos }));
  toast(p.needs && !GUIDED.photos.length ? `Add ${p.needs}, replace anything in [brackets], then press Run.` : /\[/.test(p.p) ? "Replace the parts in [brackets] with your own words, then press Run." : "Ready: check it, then press Run.", 7000);
};
$("#gdGo").onclick = async () => {
  const want = $("#gdWant").value.trim(); if (!want) return toast("Say what you'd like to make, even roughly.");
  const budget = $("#gdBudget").value, list = MODELS.filter(m => CURATED.test(m.id)).map(m => `${m.id} | ${m.name} | ${m.cat} | ${money(m.cost.usd)}${unit(m.cost)}`).join("\n");
  $("#gdGo").disabled = true; $("#gdGo").textContent = "Setting it up…";
  try {
    const plan = jsonIn(await write(`You are Muselight's creative director. The user describes what they want; you choose the single best model from the list and write an expert prompt for it.
Rules: choose only an id from the list. If they attached photos, choose a model whose category takes images (image-to-image / edit for pictures, image-to-video for video) and refer to "the reference image". Budget: ${budget === "best" ? "best possible quality, price matters little" : budget === "cheap" ? "as cheap as possible while still good" : "good quality at a sensible price"}.
Write the prompt the way an expert would for that model: specific subject, setting, composition, lighting, style, and for video the motion and camera. Keep any @Names exactly as written and any text they want shown.
Reply with only JSON: {"model": id, "prompt": str, "aspect": one of "1:1","4:5","9:16","16:9" or null, "duration": seconds or null, "why": one short sentence on why this model, "tips": [up to 2 short tips]}.
Models (id | name | category | list price):
${list}`, `${want}${GUIDED.photos.length ? `\n(${GUIDED.photos.length} photo${GUIDED.photos.length === 1 ? "" : "s"} attached)` : ""}${ACC.library.length ? `\nTheir Library: ${ACC.library.map(li => "@" + libTag(li.name)).join(", ")}` : ""}`, GUIDED.photos.slice(0, 2)), "{");
    if (!byId(plan.model)) throw new Error("The guide picked a model that isn't available. Try again.");
    GUIDED.plan = plan; drawPlan();
  } catch (e) { toast(e.message, 7000); }
  $("#gdGo").disabled = false; $("#gdGo").textContent = "✦ Set it up";
};
async function drawPlan() {
  const p = GUIDED.plan, box = $("#gdPlan");
  box.hidden = !p; if (!p) return;
  const m = byId(p.model);
  box.innerHTML = `<div class="picker"><div class="chosen">${chosenHtml(m)}</div></div><p class="muted small">${esc(p.why || "")}</p>
    <label class="field">Prompt<span class="hint">Written for this model. Change anything you like.</span><textarea id="gdPrompt">${esc(p.prompt || "")}</textarea></label>
    ${(p.tips || []).length ? `<ul class="tips">${p.tips.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    <div class="runbar"><button class="btn small ghost" id="gdAdjust">Adjust all settings</button><span class="price" id="gdPrice"></span><button class="btn primary" id="gdRun">Make it</button></div>`;
  promptHelp($("#gdPrompt"), () => m);
  const input = async () => fillFor(await schemaOf(m.id), { prompt: $("#gdPrompt").value.trim(), images: GUIDED.photos, aspect: p.aspect, duration: p.duration });
  try { $("#gdPrice").textContent = "This run: " + money((await quote(m.id, await input())).price); } catch {}
  $("#gdRun").onclick = async () => { $("#gdRun").disabled = true; try { await launch(m.id, await input(), "Guided"); } catch (e) { toast(e.message, 6000); } $("#gdRun").disabled = false; };
  $("#gdAdjust").onclick = async () => { const v = await input(); go(kind(m) === "video" ? "video" : kind(m) === "image" ? "image" : "simple"); C.pick(m, v); };
}

// ---------- Ads: a shop link straight to a video ad ----------
$("#mkQuick").onclick = async () => {
  const url = $("#mkUrl").value.trim(); if (!url) return toast("Paste a product link first.");
  $("#mkQuick").disabled = true; $("#mkQuick").textContent = "Reading the link…";
  try {
    const r = await api("/v1/product", { url });
    if (!r.images.length) throw new Error("That page has no product photos Muselight can use. Upload some, then use Create the campaign.");
    Object.assign(MK, { name: r.name || MK.name, brief: r.description || MK.brief, product: r.images, modes: ["ugc"], formats: ["9:16"], n: 1, video: true, concepts: null, script: "" });
    if (!MK.hook) MK.hook = MK_HOOKS[1];
    saveMK(); drawMarketing();
    const [im, vm] = [await modelFor(MK.model, true), MK.videoModel], [is, vs] = [await schemaOf(im), await schemaOf(vm)];
    const [qi, qv] = await Promise.all([quote(im, fillFor(is, { prompt: "x", images: r.images.slice(0, 5), aspect: "9:16" })), quote(vm, fillFor(vs, { prompt: "x", images: [r.images[0]], duration: 5 }))]).catch(() => [null, null]);
    if (await dialog("Video ad from this link", `<p class="muted">Muselight makes a phone-style 9:16 picture of ${esc(r.name || "the product")} in use, then turns it into a 5-second video ad${qi && qv ? `, for about ${money(qi.price + qv.price)}` : ""}. Change the style, hook or models below first if you like.</p>`, "Make the video ad")) $("#mkGo").click();
  } catch (e) { toast(e.message, 8000); }
  $("#mkQuick").disabled = false; $("#mkQuick").textContent = "Video ad from link";
};

// ---------- Social › Story series: emotional multi-part drama made for short-form feeds ----------
const NICHES = {
  family: ["Family drama", "betrayal, secrets, inheritance, in-laws, a child caught in the middle"],
  romance: ["Romance and heartbreak", "cheating, second chances, wedding-day twists, a love that was there all along"],
  karma: ["Revenge and karma", "someone cruel or arrogant gets exactly what they deserve"],
  riches: ["Rags to riches", "an underdog is looked down on, then the truth about them is revealed"],
  mystery: ["Mystery and suspense", "a disappearance, a locked room, a stranger who knows too much"],
  wholesome: ["Wholesome and kind", "kids, pets, the elderly, strangers helping each other; happy tears"],
  workplace: ["Workplace drama", "a cruel boss, a promotion, a secret, a dramatic resignation"],
  school: ["School and teen drama", "bullies, friendships, a talent show, a secret crush"],
  historical: ["Historical drama", "another era: forbidden love, war, class divides"],
  twist: ["Supernatural twist", "an ordinary day where one impossible thing happens"],
};
const LOOKS = {
  Realistic: {
    "90s family film": "the look of an early-1990s Hollywood family film: warm tungsten interiors, soft diffusion, 35mm film grain, rich reds and greens, a cosy suburban American home, an attractive natural-looking cast, nostalgic and familiar",
    "80s soap opera": "a 1980s TV soap-opera look: soft-focus glow, glamorous styling, VHS colour, dramatic close-ups",
    "Modern streaming drama": "a modern prestige streaming-drama look: moody cinematic lighting, shallow depth of field, a teal-and-orange grade",
    "K-drama": "a glossy Korean-drama look: soft pastel light, beautiful clean interiors, gentle lens flares, romantic framing",
    "Telenovela": "a telenovela look: bright high-key lighting, saturated colour, dramatic zooms onto shocked faces",
    "Phone footage": "realistic vertical smartphone footage, handheld, natural light, as if filmed by someone in the room",
    "True-crime documentary": "a true-crime documentary look: interview lighting, muted colour, archival textures",
    "1950s Americana": "a 1950s Technicolor look: pastel kitchens, polished cars, warm saturated colour",
  },
  Animated: {
    "3D animated film": "a polished 3D animated feature-film style with expressive original characters and soft global illumination",
    "Anime": "a detailed Japanese anime style with clean line art, soft cel shading and painterly backgrounds",
    "90s Saturday-morning cartoon": "a 1990s hand-drawn TV cartoon style with bold outlines and flat colours",
    "Claymation": "a handmade stop-motion claymation style with visible fingerprints and miniature sets",
    "Storybook": "a soft watercolour storybook illustration style",
    "Comic book": "a bold comic-book style with ink lines, halftone shading and vivid colour",
  },
};
const LOOK_TEXT = Object.assign({}, ...Object.values(LOOKS));
const VOICES = ["Rachel", "Sarah", "Laura", "Charlotte", "Alice", "Matilda", "Jessica", "Lily", "Aria", "River", "Roger", "George", "Callum", "Liam", "Will", "Eric", "Chris", "Brian", "Daniel", "Bill", "Charlie"];
const SR = Object.assign({ niche: "family", look: "90s family film", audience: "women 25-45", idea: "", parts: 3, scenes: 6, secs: 5, sound: "narrator", voice: "Rachel", subtitles: true,
  imageModel: "fal-ai/nano-banana-2", videoModel: "fal-ai/kling-video/v3/standard/image-to-video", bible: null }, JSON.parse(store.get("ml_series") || "{}"));
const saveSR = () => store.set("ml_series", JSON.stringify(SR));
function drawSeries() {
  $("#srNiche").innerHTML = Object.entries(NICHES).map(([k, [l]]) => `<option value="${k}"${k === SR.niche ? " selected" : ""}>${l}</option>`).join("");
  $("#srLook").innerHTML = Object.entries(LOOKS).map(([g, o]) => `<optgroup label="${g}">${Object.keys(o).map(l => `<option${l === SR.look ? " selected" : ""}>${esc(l)}</option>`).join("")}</optgroup>`).join("");
  $("#srVoice").innerHTML = VOICES.map(v => `<option${v === SR.voice ? " selected" : ""}>${v}</option>`).join("");
  for (const [id, k] of [["#srAud", "audience"], ["#srIdea", "idea"], ["#srParts", "parts"], ["#srScenes", "scenes"], ["#srSecs", "secs"], ["#srSound", "sound"]]) $(id).value = SR[k];
  $("#srSubs").checked = SR.subtitles; $("#srVoiceRow").hidden = SR.sound !== "narrator";
  if (!byId(SR.imageModel)) SR.imageModel = ["fal-ai/nano-banana-2", "fal-ai/nano-banana", "fal-ai/flux/dev"].find(byId) || SR.imageModel;
  if (!byId(SR.videoModel)) SR.videoModel = MODELS.find(isVideoModel)?.id || SR.videoModel;
  chooser($("#srImg"), SR, "imageModel", isImageModel, saveSR);
  chooser($("#srVid"), SR, "videoModel", isVideoModel, saveSR);
  drawBible();
}
for (const [id, k, num] of [["#srNiche", "niche"], ["#srLook", "look"], ["#srAud", "audience"], ["#srIdea", "idea"], ["#srParts", "parts", 1], ["#srScenes", "scenes", 1], ["#srSecs", "secs", 1], ["#srVoice", "voice"], ["#srSound", "sound"]])
  $(id).onchange = () => { SR[k] = num ? +$(id).value : $(id).value; saveSR(); if (k === "sound") $("#srVoiceRow").hidden = SR.sound !== "narrator"; };
$("#srSubs").onchange = () => { SR.subtitles = $("#srSubs").checked; saveSR(); };
$("#srWrite").onclick = async () => {
  if (SR.bible && !confirm("Write a new series? The current one is replaced (its videos stay in History).")) return;
  $("#srWrite").disabled = true; $("#srWrite").textContent = "Writing the series…";
  const words = Math.round(SR.scenes * SR.secs * 2.3), lib = ACC.library.filter(li => li.kind === "character").map(li => "@" + libTag(li.name)).join(", ");
  try {
    const b = jsonIn(await write(`You write viral short-form drama series for TikTok, Reels and Shorts. Every part must hook in the first two seconds, build strong emotion (shock, injustice, tenderness, vindication) and keep people watching. Every part except the last ends on a cliffhanger that makes people need the next part.
Only ever use original characters: never real people, celebrities, or existing characters from films, shows, games or books. Give each character a one-word first name.
Visual style for every shot: ${LOOK_TEXT[SR.look]}. Vertical 9:16 frames.
In each scene's "image", refer to characters as @Name (the @ then their one-word name) and describe the shot's first frame: who, where, framing, expressions, lighting. In "motion", describe what happens in the ${SR.secs} seconds and how the camera moves.
${SR.sound === "narrator" ? `Each part has "narration": a dramatic first-person or narrator voice-over of about ${words} words (it must fit ${SR.scenes * SR.secs} seconds), written to be spoken aloud.` : `Each scene has "line": one short line of dialogue the main character in it says, written as Name: "line".`}
Reply with only JSON: {"title": str, "logline": str, "cast": [{"name": str, "role": str, "look": a detailed, specific visual description that stays the same in every shot (age, face, hair, build, clothing)}], "parts": [{"title": str, "hook": the on-screen text for the first second, "cliffhanger": str, "caption": a social caption with 3-5 hashtags including #AI and "Part N"${SR.sound === "narrator" ? `, "narration": str` : ""}, "scenes": [{"image": str, "motion": str${SR.sound === "narrator" ? "" : `, "line": str`}}]}]}`,
      `Niche: ${NICHES[SR.niche][0]} (${NICHES[SR.niche][1]}). Audience: ${SR.audience}. ${SR.parts} parts, ${SR.scenes} scenes per part.${SR.idea.trim() ? `\nThe story idea: ${SR.idea.trim()}` : "\nInvent a fresh, gripping story idea."}${lib ? `\nThey may use these existing characters from their Library: ${lib}.` : ""}`), "{");
    if (!b.parts?.length || !b.cast?.length) throw new Error("The series came back incomplete. Try again.");
    b.id = Date.now().toString(36); SR.bible = b; saveSR(); drawBible();
  } catch (e) { toast(e.message, 8000); }
  $("#srWrite").disabled = false; $("#srWrite").textContent = "✦ Write the series";
};
function drawBible() {
  const b = SR.bible, box = $("#srBible"); box.hidden = !b; if (!b) return;
  const castItem = c => ACC.library.find(li => li.name === c.name && li.kind === "character");
  box.innerHTML = `<h3 class="subhead">${esc(b.title)}</h3><p class="muted">${esc(b.logline || "")}</p>
    <div class="field"><label class="field">Cast<span class="hint">Each gets a reference portrait in your Library, so they look the same in every shot</span></label>
      <div class="cast">${b.cast.map((c, i) => { const li = castItem(c); return `<div class="castcard">${li?.files?.[0] ? `<img src="${esc(li.files[0])}" alt="">` : `<span class="noimg">@</span>`}<b>@${esc(libTag(c.name))}</b><span>${esc(c.role || "")}</span>${li?.files?.length && li.series !== b.id ? `<span>From your Library</span>` : `<button class="btn small ghost" data-cast="${i}">${li?.files?.length ? "Remake" : "Make portrait"}</button>`}</div>`; }).join("")}</div>
      <button class="btn small" id="srCast">Make the whole cast</button></div>
    ${b.parts.map((p, pi) => `<div class="step part"><div class="stephead"><b>Part ${pi + 1}: ${esc(p.title || "")}</b><span class="grow"></span><span class="muted small" id="srStat${pi}">${esc(p.status || "")}</span></div>
      <p class="muted small"><b>Hook:</b> ${esc(p.hook || "")} · <b>Cliffhanger:</b> ${esc(p.cliffhanger || "")}</p>
      ${p.narration != null ? `<label class="field">Narration<textarea data-p="${pi}" data-f="narration">${esc(p.narration)}</textarea></label>` : ""}
      <details class="more"><summary>${p.scenes.length} scenes</summary><div class="form">${p.scenes.map((s, si) => `<div class="scene"><b>Scene ${si + 1}</b>${s.key ? `<img src="${esc(s.key)}" alt="">` : ""}<textarea data-p="${pi}" data-s="${si}" data-f="image">${esc(s.image)}</textarea><textarea data-p="${pi}" data-s="${si}" data-f="motion" style="min-height: 50px">${esc(s.motion || "")}</textarea>${s.line != null ? `<input data-p="${pi}" data-s="${si}" data-f="line" value="${esc(s.line)}">` : ""}</div>`).join("")}</div></details>
      ${p.final ? `<video src="${esc(p.final)}" controls playsinline class="final"></video><div class="row"><a class="btn small primary" href="${esc(p.final)}" target="_blank" rel="noopener" download>Download</a><button class="btn small" data-copy="${pi}">Copy caption</button></div><p class="muted small">${esc(p.caption || "")}</p>` : ""}
      <button class="btn small${p.final ? "" : " primary"}" data-make="${pi}">${p.final ? "Make it again" : p.status ? "Carry on making it" : `Make part ${pi + 1}`}</button></div>`).join("")}
    <p class="muted small">AI-made people should be labelled as AI where you post them: TikTok, Instagram and YouTube ask for it, and the captions include #AI.</p>`;
  box.querySelectorAll("[data-f]").forEach(t => t.onchange = () => { const p = b.parts[+t.dataset.p]; (t.dataset.s != null ? p.scenes[+t.dataset.s] : p)[t.dataset.f] = t.value; saveSR(); });
  box.querySelectorAll("[data-cast]").forEach(x => x.onclick = () => makeCast([b.cast[+x.dataset.cast]]));
  box.querySelectorAll("[data-make]").forEach(x => x.onclick = () => makePart(+x.dataset.make));
  box.querySelectorAll("[data-copy]").forEach(x => x.onclick = () => navigator.clipboard.writeText(b.parts[+x.dataset.copy].caption || "").then(() => toast("Caption copied.")));
  $("#srCast").onclick = () => makeCast(b.cast);
}
async function makeCast(cast) {
  const id = SR.imageModel, s = await schemaOf(id);
  const own = cast.filter(c => { const li = ACC.library.find(x => x.name === c.name && x.files?.length); return li && li.series !== SR.bible.id; });
  if (own.length) toast(`${own.map(c => "@" + c.name).join(", ")} ${own.length === 1 ? "is" : "are"} already in your Library, so ${own.length === 1 ? "that picture is" : "those pictures are"} used.`, 6000);
  await Promise.all(cast.filter(c => !own.includes(c)).map(async c => {
    try {
      const run = await launch(id, fillFor(s, { prompt: `Character reference portrait of ${c.look}. Head and shoulders, facing the camera, neutral expression, plain background, sharp detail. ${LOOK_TEXT[SR.look]}.`, aspect: "4:5" }), `Cast · ${c.name}`);
      if (run.status !== "done") throw new Error(run.error || "it didn't work");
      const li = ACC.library.find(x => x.name === c.name && x.kind === "character");
      if (li) Object.assign(li, { files: [run.outputs[0]], notes: c.look });
      else ACC.library.push({ id: Date.now().toString(36) + c.name, name: c.name, kind: "character", files: [run.outputs[0]], notes: c.look, series: SR.bible.id });
      keep("library"); drawBible();
    } catch (e) { toast(`${c.name}'s portrait: ${e.message}`, 6000); }
  }));
}
// a part: keyframes and clips for every scene, then the voice-over, joined, with subtitles. Finished pieces are kept, so it can carry on after a failure.
async function makePart(pi) {
  const b = SR.bible, p = b.parts[pi], stat = t => { p.status = t; saveSR(); const el = $("#srStat" + pi); if (el) el.textContent = t; };
  const missingCast = b.cast.filter(c => !ACC.library.find(li => li.name === c.name && li.files?.length));
  if (missingCast.length && !confirm(`${missingCast.map(c => c.name).join(", ")} ${missingCast.length === 1 ? "has" : "have"} no portrait yet, so they may look different in each shot. Make the part anyway?`)) return;
  try {
    const im = await modelFor(SR.imageModel, true), is = await schemaOf(im), bs = await schemaOf(SR.imageModel), vs = await schemaOf(SR.videoModel);
    // scenes with cast in them use the model that takes their pictures (its edit version); the rest use the model as chosen.
    // A model that can't take pictures at all gets the cast's descriptions instead.
    const withCast = sc => /@\w/.test(sc.image), keyModel = sc => withCast(sc) ? im : SR.imageModel;
    const refs = fileFields(is).some(f => f.kind === "image"), named = t => refs ? t : t.replace(/@(\w+)/g, (m, n) => { const c = b.cast.find(c => libTag(c.name).toLowerCase() === n.toLowerCase()); return c ? `${c.name} (${c.look})` : n; });
    const keyIn = sc => fillFor(withCast(sc) ? is : bs, { prompt: `${named(sc.image)}\n\nStyle: ${LOOK_TEXT[SR.look]}.`, aspect: "9:16" });
    const vidIn = sc => {
      // the keyframe already shows who is who, so names in the motion are plain words, not @mentions
      const v = fillFor(vs, { prompt: `${sc.motion || ""}${sc.line ? ` ${sc.line}` : ""}`.trim().replace(/@(\w+)/g, "$1"), images: [sc.key], duration: SR.secs, aspect: "9:16" });
      for (const k of Object.keys(vs.properties || {})) if (/generate_audio|with_audio|enable_audio/.test(k)) v[k] = SR.sound !== "narrator";
      return v;
    };
    const tts = ["fal-ai/elevenlabs/tts/eleven-v3", "fal-ai/elevenlabs/tts/multilingual-v2"].find(byId);
    const steps = p.scenes.filter(sc => !sc.key).length, clips = p.scenes.filter(sc => !sc.vid).length;
    const prices = await Promise.all([quote(im, keyIn({ image: "@x" })), quote(SR.videoModel, vidIn({ motion: "x", key: "https://v3.fal.media/files/sample/sample.png" })), SR.sound === "narrator" && tts ? quote(tts, { text: p.narration || "x", voice: SR.voice }) : { price: 0 }]).catch(() => null);
    const total = prices ? prices[0].price * steps + prices[1].price * clips + prices[2].price + 0.05 : null;
    if (!(await dialog(`Make part ${pi + 1}`, `<p class="muted">${steps ? `${steps} keyframe${steps === 1 ? "" : "s"}, ` : ""}${clips ? `${clips} video clip${clips === 1 ? "" : "s"}, ` : ""}${SR.sound === "narrator" ? "the voice-over, " : ""}then joined into one ${p.scenes.length * SR.secs}-second vertical video${SR.subtitles ? " with subtitles" : ""}${total != null ? `, for about <b>${money(total)}</b>` : ""}. Keep this page open while it's made (a few minutes).</p>`, "Make it"))) return;
    stat("Making keyframes…");
    await Promise.all(p.scenes.map(async (sc, i) => { if (sc.key) return; const r = await launch(keyModel(sc), keyIn(sc), `Part ${pi + 1} · scene ${i + 1}`); if (r.status !== "done") throw new Error(`Scene ${i + 1}'s keyframe didn't work${r.error ? ": " + r.error : ""}`); sc.key = r.outputs[0]; saveSR(); }));
    drawBible(); stat("Animating the scenes…");
    await Promise.all(p.scenes.map(async (sc, i) => { if (sc.vid) return; const r = await launch(SR.videoModel, vidIn(sc), `Part ${pi + 1} · clip ${i + 1}`); if (r.status !== "done") throw new Error(`Scene ${i + 1}'s clip didn't work${r.error ? ": " + r.error : ""}`); sc.vid = r.outputs[0]; saveSR(); }));
    const film = [{ model: "fal-ai/ffmpeg-api/merge-videos", input: { video_urls: p.scenes.map(sc => sc.vid) } }];
    if (SR.sound === "narrator" && tts && p.narration) {
      if (p.voiceFor !== p.narration + SR.voice) {  // recorded again only when the words or the voice changed
        stat("Recording the voice-over…");
        const v = await launch(tts, { text: p.narration, voice: SR.voice }, `Part ${pi + 1} · voice-over`);
        if (v.status !== "done") throw new Error("The voice-over didn't work" + (v.error ? ": " + v.error : ""));
        Object.assign(p, { voice: v.outputs[0], voiceFor: p.narration + SR.voice }); saveSR();
      }
      film.push({ model: "fal-ai/ffmpeg-api/merge-audio-video", input: { video_url: PREV, audio_url: p.voice } });
    }
    if (SR.subtitles && byId("fal-ai/workflow-utilities/auto-subtitle")) film.push({ model: "fal-ai/workflow-utilities/auto-subtitle", input: { video_url: PREV, words_per_subtitle: 3, highlight_color: "yellow", font_size: 80, position: "bottom", y_offset: 180 } });
    stat("Putting it together…");
    p.final = await chain(film, `Part ${pi + 1}`);
    stat("Done"); drawBible(); toast(`Part ${pi + 1} is ready.`);
  } catch (e) { stat("Stopped: " + e.message); toast(e.message + ". Press the button again to carry on from where it stopped; finished scenes are kept.", 9000); drawBible(); }
}

// ---------- Social › AI influencer: a fictional creator with one face, then their posts and talking videos ----------
const INF_NICHES = ["Fitness", "Fashion", "Beauty", "Travel", "Food", "Tech", "Gaming", "Lifestyle", "Finance", "Parenting", "Music", "Art", "Wellness", "Pets"];
const AESTHETICS = ["Clean and natural", "Luxury", "Streetwear", "Cottagecore", "Sporty", "Y2K", "Minimal", "Boho", "Glam", "Edgy", "Preppy", "Outdoorsy"];
const INF = { draft: { name: "", niche: "Lifestyle", aesthetic: "Clean and natural", look: "", personality: "", voice: "Rachel" }, faces: [], who: store.get("ml_inf") || "", ideas: [] };
const influencers = () => ACC.library.filter(li => li.kind === "character" && li.influencer);
function drawInfluencer() {
  const list = influencers(), d = INF.draft;
  if (INF.who && !list.some(li => li.name === INF.who)) INF.who = "";
  $("#infWho").innerHTML = list.map(li => `<option${li.name === INF.who ? " selected" : ""}>${esc(li.name)}</option>`).join("") + `<option value=""${INF.who ? "" : " selected"}>＋ A new influencer</option>`;
  const li = list.find(x => x.name === INF.who);
  $("#infNew").hidden = !!li; $("#infStudio").hidden = !li;
  if (!li) {
    $("#infNiche").innerHTML = INF_NICHES.map(n => `<option${n === d.niche ? " selected" : ""}>${n}</option>`).join("");
    $("#infAes").innerHTML = AESTHETICS.map(n => `<option${n === d.aesthetic ? " selected" : ""}>${n}</option>`).join("");
    $("#infVoice").innerHTML = VOICES.map(v => `<option${v === d.voice ? " selected" : ""}>${v}</option>`).join("");
    for (const [id, k] of [["#infName", "name"], ["#infLook", "look"], ["#infPers", "personality"]]) $(id).value = d[k];
    $("#infFaces").innerHTML = INF.faces.map((u, i) => `<button type="button" data-i="${i}"><img src="${esc(u)}" alt=""></button>`).join("");
    $("#infFaces").hidden = !INF.faces.length; $("#infPick").hidden = !INF.faces.length;
    $("#infFaces").querySelectorAll("button").forEach(b => b.onclick = () => chooseFace(INF.faces[+b.dataset.i]));
    return;
  }
  $("#infCard").innerHTML = `${li.files?.[0] ? `<img src="${esc(li.files[0])}" alt="">` : ""}<div><b>@${esc(libTag(li.name))}</b><span>${esc(li.influencer.niche)} · ${esc(li.influencer.aesthetic)}</span><span>${esc(li.influencer.personality || "")}</span><span class="muted small">${li.files?.length || 0} reference pictures${li.lora ? " · identity trained" : ""}</span></div>`;
  $("#infIdeas").innerHTML = INF.ideas.map((x, i) => `<div class="idea"><div class="grow"><b>${esc(x.title || "Post " + (i + 1))}</b><span>${esc(x.caption || "")}</span></div><button class="btn small" data-i="${i}">Make it</button></div>`).join("");
  $("#infIdeas").querySelectorAll("[data-i]").forEach(b => b.onclick = () => makePost(li, INF.ideas[+b.dataset.i]));
}
for (const [id, k] of [["#infName", "name"], ["#infLook", "look"], ["#infPers", "personality"], ["#infNiche", "niche"], ["#infAes", "aesthetic"], ["#infVoice", "voice"]]) $(id).onchange = () => INF.draft[k] = $(id).value.trim();
$("#infWho").onchange = () => { INF.who = $("#infWho").value; store.set("ml_inf", INF.who || null); INF.ideas = []; drawInfluencer(); };
$("#infFill").onclick = async () => {
  const d = INF.draft; $("#infFill").disabled = true;
  try {
    const r = jsonIn(await write("You design fictional social media influencers. They must be clearly fictional: never based on, named after or resembling a real person or celebrity. Reply with only JSON.",
      `Niche: ${d.niche}. Aesthetic: ${d.aesthetic}.${d.name ? ` Name: ${d.name}.` : ""}${d.look ? ` Look so far: ${d.look}.` : ""}\nReply as {"name": a one-word first name, "look": a detailed, specific description of their face, age, hair, skin, build and signature style that an image model can reproduce, "personality": one sentence on how they talk and what they care about}.`), "{");
    Object.assign(d, { name: d.name || r.name || "", look: r.look || d.look, personality: r.personality || d.personality }); drawInfluencer();
  } catch (e) { toast(e.message, 6000); }
  $("#infFill").disabled = false;
};
$("#infDesign").onclick = async () => {
  const d = INF.draft;
  if (!d.name || !d.look) return toast("Give them a name and describe their look, or press “Fill in for me”.");
  if (ACC.library.some(li => li.name.toLowerCase() === d.name.toLowerCase())) return toast(`There's already a Library element called ${d.name}. Pick another name.`);
  const id = ["fal-ai/nano-banana-2", "fal-ai/nano-banana", "fal-ai/flux/dev"].find(byId), s = await schemaOf(id);
  const input = fillFor(s, { prompt: `Natural, candid portrait photo of a fictional ${d.niche.toLowerCase()} influencer: ${d.look}. ${d.aesthetic} style. Head and shoulders, soft daylight, realistic skin texture, looking at the camera, like a real social media profile photo.`, aspect: "4:5" });
  let price = ""; try { price = money((await quote(id, input)).price * 4); } catch {}
  if (!(await dialog("Design the face", `<p class="muted">Four different faces for ${esc(d.name)} from your description${price ? `, for about ${price}` : ""}. You pick the one you like.</p>`, "Make 4 faces"))) return;
  $("#infDesign").disabled = true; INF.faces = []; drawInfluencer();
  const runs = await Promise.allSettled([0, 1, 2, 3].map(i => launch(id, input, `${d.name} · face ${i + 1}`)));
  INF.faces = runs.filter(r => r.status === "fulfilled" && r.value.status === "done").map(r => r.value.outputs[0]);
  if (!INF.faces.length) toast("The faces didn't come out. Try again.", 6000);
  $("#infDesign").disabled = false; drawInfluencer();
};
async function chooseFace(u) {
  const d = INF.draft;
  ACC.library.push({ id: Date.now().toString(36), name: d.name, kind: "character", files: [u], notes: d.look, voice: d.voice, influencer: { niche: d.niche, aesthetic: d.aesthetic, personality: d.personality } });
  keep("library"); INF.who = d.name; store.set("ml_inf", d.name); INF.faces = []; INF.draft = { ...INF.draft, name: "", look: "", personality: "" }; drawInfluencer();
  toast(`${d.name} is saved in your Library. Next: “Build a reference set” so their face stays the same everywhere.`, 7000);
}
const inf = () => influencers().find(li => li.name === INF.who);
$("#infRefs").onclick = async () => {
  const li = inf(); if (!li?.files?.[0]) return;
  const id = ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"].find(byId), s = await schemaOf(id);
  const views = ["three-quarter view from the left, smiling", "side profile", "full body, standing, in their signature outfit", "close-up with natural expression, different lighting"];
  if (!(await dialog("Build a reference set", `<p class="muted">Four more pictures of ${esc(li.name)} from new angles, made from their face. More reference pictures keep them the same in every post and video.</p>`, "Make 4 pictures"))) return;
  const runs = await Promise.allSettled(views.map(v => launch(id, fillFor(s, { prompt: `The same person as the reference image, identical face, hair and identity: ${v}. Realistic photo.`, images: [li.files[0]], aspect: "4:5" }), `${li.name} · reference`)));
  li.files.push(...runs.filter(r => r.status === "fulfilled" && r.value.status === "done").map(r => r.value.outputs[0]));
  keep("library"); drawInfluencer(); toast(`${li.name} now has ${li.files.length} reference pictures.`);
};
$("#infIdeasBtn").onclick = async () => {
  const li = inf(); if (!li) return;
  $("#infIdeasBtn").disabled = true;
  try {
    INF.ideas = jsonIn(await write("You are a social media strategist for a fictional influencer. Reply with only JSON.",
      `Influencer @${libTag(li.name)}: ${li.influencer.niche}, ${li.influencer.aesthetic} style. Personality: ${li.influencer.personality || "-"}.\nWrite 8 varied post ideas that would do well right now: a mix of photo dumps, outfit or product shots, behind-the-scenes and relatable moments. Reply as [{"title": short, "scene": one string: a specific photo prompt that includes @${libTag(li.name)} and covers the setting, outfit, pose, light and phone-photo realism, "caption": the caption in their voice with 2-4 hashtags}].`), "[")
      .map(x => ({ ...x, scene: typeof x.scene === "string" ? x.scene : Object.values(x.scene || {}).join(" ") }));
    drawInfluencer();
  } catch (e) { toast(e.message, 6000); }
  $("#infIdeasBtn").disabled = false;
};
async function makePost(li, idea) {
  const id = ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"].find(byId), s = await schemaOf(id);
  try { const run = await launch(id, fillFor(s, { prompt: idea.scene, aspect: "4:5" }), `${li.name} · ${idea.title || "post"}`); if (run.status === "done") { navigator.clipboard?.writeText(idea.caption || "").catch(() => {}); toast("Post made. Its caption is copied, ready to paste."); } }
  catch (e) { toast(e.message, 6000); }
}
$("#infDump").onclick = () => { const li = inf(); if (li) photoSet(li); };
$("#infScriptBtn").onclick = async () => {
  const li = inf(); if (!li) return;
  $("#infScriptBtn").disabled = true;
  try { $("#infScript").value = (await write(`You write short talking-to-camera scripts for a fictional ${li.influencer.niche.toLowerCase()} influencer. Personality: ${li.influencer.personality || "-"}. Reply with only the words they say: natural, spoken, 20-40 words, a hook in the first sentence.`, $("#infTopic").value.trim() || "Something their followers would love today")).trim(); }
  catch (e) { toast(e.message, 6000); }
  $("#infScriptBtn").disabled = false;
};
$("#infTalk").onclick = async () => {
  const li = inf(), text = $("#infScript").value.trim();
  if (!li?.files?.[0]) return; if (!text) return toast("Write what they say, or press “Write it for me”.");
  const tts = ["fal-ai/elevenlabs/tts/eleven-v3", "fal-ai/elevenlabs/tts/multilingual-v2"].find(byId), av = ["fal-ai/kling-video/ai-avatar/v2/standard", "veed/fabric-1.0", "fal-ai/bytedance/omnihuman/v1.5"].find(byId);
  if (!tts || !av) return toast("Talking videos aren't available right now.");
  const secs = Math.max(3, Math.round(text.split(/\s+/).length / 2.5));
  if (secs > 15) return toast("Keep it to about 35 words: talking videos are up to 15 seconds.");
  let price = ""; try { const [a, b] = await Promise.all([quote(tts, { text, voice: li.voice || "Rachel" }), quote(av, fillFor(await schemaOf(av), { images: [li.files[0]], audios: ["https://v3.fal.media/x.mp3"] }))]); price = money(a.price + b.price); } catch {}
  if (!(await dialog("Talking video", `<p class="muted">${esc(li.name)} says it in the ${esc(li.voice || "Rachel")} voice, about ${secs} seconds${price ? `, for about ${price}` : ""}.</p>`, "Make it"))) return;
  try {
    const steps = [{ model: tts, input: { text, voice: li.voice || "Rachel" } }, { model: av, input: fillFor(await schemaOf(av), { prompt: "talking naturally to the camera, subtle head movement", images: [li.files[0]], audios: [PREV] }) }];
    if ($("#infSubs").checked && byId("fal-ai/workflow-utilities/auto-subtitle")) steps.push({ model: "fal-ai/workflow-utilities/auto-subtitle", input: { video_url: PREV, words_per_subtitle: 3, highlight_color: "yellow" } });
    await chain(steps, `${li.name} · talking`); toast("The talking video is ready under Latest.");
  } catch (e) { toast(e.message, 7000); }
};

// ---------- more Apps: one-click edits written as prompts, and video finishing tools ----------
const EDITOR = () => ["fal-ai/nano-banana-2/edit", "fal-ai/nano-banana/edit"].find(byId);
APPS.push(
  { label: "Retouch skin", desc: "Natural, clean skin", image: "fal-ai/image-editing/retouch" },
  { label: "Headshot", desc: "A professional portrait from it", image: "fal-ai/image-apps-v2/headshot-photo" },
  { label: "Face swap", desc: "Put another face in the picture", image: "faceswap" },
  { label: "Change the outfit", desc: "Same person, new clothes", image: "editor", prompt: "Change the outfit of the person in the image to: [describe the new outfit]. Keep their face, pose, hair, body and the background exactly the same." },
  { label: "Change the background", desc: "Same subject somewhere else", image: "editor", prompt: "Keep the subject exactly as it is and place it in: [describe the new background]. Match the lighting and shadows naturally." },
  { label: "Product placement", desc: "Put your product in the scene", image: "editor", prompt: "Place the product from the second image naturally into the first image: [where, e.g. in her hand / on the table]. Keep the product's shape, colours and label exactly the same. Match the lighting." },
  { label: "Character sheet", desc: "Front, side and back views", image: "editor", prompt: "Character turnaround sheet of the character in the image: front view, three-quarter view, side view and back view side by side, full body, plain light background, identical design and outfit in every view." },
  { label: "Restyle", desc: "Redraw it in another style", image: "editor", prompt: "Redraw this image in [the style, e.g. Studio-style anime / oil painting / claymation]. Keep the composition, subject and pose the same." },
  { label: "Talking photo", desc: "Make the face speak", image: "fal-ai/kling-video/ai-avatar/v2/standard" },
  { label: "Slow motion", desc: "Smooth in-between frames", video: "fal-ai/rife/video" },
  { label: "Add sound effects", desc: "Sound made to fit the video", video: "fal-ai/mmaudio-v2" },
  { label: "Add music", desc: "A soundtrack made for it", video: "sonilo/v1.1/video-to-video-music" },
  { label: "Subtitles", desc: "Word-by-word captions", video: "fal-ai/workflow-utilities/auto-subtitle" },
  { label: "Translate and dub", desc: "Same voice, another language", video: "fal-ai/heygen/v2/translate/speed" },
);
SPECIAL.push("faceswap", "editor");
async function faceSwap(u) {
  const d = await dialog("Face swap", `<p class="muted">Puts the face from a photo you add onto this picture.</p>
    <label class="field">The face to use<input type="file" id="fsFile" accept="image/*"></label>
    <label class="agree"><input type="checkbox" id="fsOk"><span>This is my face, or I have the person's permission. I won't use it to deceive, harass or impersonate anyone.</span></label>`, "Set it up");
  if (!d) return;
  const f = d.querySelector("#fsFile").files[0];
  if (!d.querySelector("#fsOk").checked) return toast("Face swap needs the box ticked: only your own face, or one you have permission to use.", 7000);
  if (!f) return toast("Add the photo of the face to use.");
  try {
    const face = await upload(f), id = EDITOR();
    go("image"); await C.pick(byId(id), fillFor(await schemaOf(id), { prompt: "Replace the face of the person in the first image with the face of the person in the second image. Keep the first image's pose, expression direction, hair, lighting, clothing and background. Photorealistic, seamless.", images: [u, face] }));
    toast("Face swap is set up. Press Run.", 6000);
  } catch (e) { toast(e.message); }
}

// ---------- Draft first, then the final with the same seed ----------
// The cheapest version of these settings: lowest resolution, quality and length, one output, faster modes, no generated sound.
function draftInputs(s, values) {
  const props = s.properties || {}, out = JSON.parse(JSON.stringify(values)), size = v => { const m = String(v).match(/(\d+(?:\.\d+)?)\s*(k|p)?/i); return m ? +m[1] * (/k/i.test(m[2] || "") ? 1000 : 1) : 1e9; };
  for (const [k, p] of Object.entries(props)) {
    const opts = p.enum || [], cur = out[k] ?? p.default;
    if (/^(num_images|num_outputs|n|number_of_images|num_videos|batch_size|max_images)$/.test(k)) { if (cur != null) out[k] = 1; continue; }
    if (/resolution|quality|^size$/.test(k) && opts.length) { const low = /quality/.test(k) ? opts.find(o => /^(low|draft|fast|standard|medium)$/i.test(o)) : [...opts].sort((a, b) => size(a) - size(b))[0]; if (low !== undefined) out[k] = low; continue; }
    if (/duration|seconds|num_frames/.test(k)) { const nums = opts.filter(o => !isNaN(parseFloat(o))); if (nums.length) out[k] = [...nums].sort((a, b) => parseFloat(a) - parseFloat(b))[0]; else if (p.minimum != null && cur != null) out[k] = p.minimum; continue; }
    if (/num_inference_steps|^steps$/.test(k) && typeof cur === "number") { out[k] = Math.max(p.minimum ?? 4, Math.round(cur / 2)); continue; }
    if (/rendering_speed|speed|acceleration|mode$/.test(k) && opts.length) { const f = opts.find(o => /^(turbo|flash|fast|high|std|standard|lite)$/i.test(o)); if (f !== undefined) out[k] = f; continue; }
    if (/generate_audio|with_audio|enable_audio/.test(k)) { out[k] = false; continue; }
    if (k === "image_size" && typeof cur === "string" && cur.endsWith("_hd")) out[k] = cur.replace(/_hd$/, "");
  }
  return out;
}
const DRAFTS = JSON.parse(store.get("ml_drafts") || "{}");
$("#draft").onclick = async () => {
  if ($("#run").disabled) return toast($("#run").title || "Fill in the settings first.");
  const values = JSON.parse(JSON.stringify(C.values)), sk = Object.keys(C.schema.properties || {}).find(k => k === "seed");
  if (sk && values.seed == null) values.seed = Math.floor(Math.random() * 2 ** 31);  // the final reuses it, so it looks the same
  const draft = draftInputs(C.schema, values);
  try {
    const q = await quote(C.model.id, draft), full = await quote(C.model.id, values);
    toast(`Draft started for ${cost(q)} (the full version is ${cost(full)}). Like it? Open it and press “Make the final version”.`, 7000);
    const run = await launch(C.model.id, draft, "Draft");
    if (run.id) { DRAFTS[run.id] = { model: C.model.id, values }; const ids = Object.keys(DRAFTS); ids.slice(0, -50).forEach(i => delete DRAFTS[i]); store.set("ml_drafts", JSON.stringify(DRAFTS)); }
  } catch (e) { toast(e.message, 6000); }
};

// ---------- when a run fails: what probably went wrong, and how to fix it ----------
function failTip(err = "") {
  const e = err.toLowerCase();
  if (/safety|nsfw|content.?polic|moderat|flagged|sensitive|not allowed/.test(e)) return "The model's safety filter stopped it. Reword anything explicit or violent, leave out real people's names, or try another model.";
  if (/face|real person|celebrit|public figure/.test(e)) return "This model turns away pictures of real people's faces. Try another model, or a picture without a recognisable face.";
  if (/required|missing|at least one/.test(e)) return "Something the model needs is missing: usually a picture, video or prompt. Fill in the boxes marked *.";
  if (/size|resolution|aspect|dimension|too (large|small)|width|height/.test(e)) return "The model didn't like the size or shape. Try another shape, or a smaller picture.";
  if (/duration|length|too long|seconds/.test(e)) return "The length isn't one this model accepts. Try a shorter or standard length.";
  if (/timeout|timed out|busy|overloaded|capacity|503|502|unavailable/.test(e)) return "The provider was busy. Try again in a minute, or pick another model.";
  if (/url|download|fetch|could not (load|read)|invalid image/.test(e)) return "The model couldn't open one of the files. Upload it again, or try a JPG or PNG.";
  return "Try again; if it fails twice, try another model or ask the assistant.";
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-ask]"); if (!b) return;
  const run = [...LATEST, ...HIST].find(r => r.id === b.dataset.ask); if (!run) return;
  $("#chat").hidden = false; drawChat();
  $("#chatIn").value = `My run with ${byId(run.model)?.name || run.model} failed: “${(run.error || "no reason given").slice(0, 300)}”. The settings were ${JSON.stringify(run.input || {}).slice(0, 600)}. What should I change?`;
  chatSend();
});

// ---------- favourites, folders and share links ----------
const favs = () => (ACC.settings.favs ||= []), folders = () => (ACC.settings.folders ||= {}), shares = () => (ACC.settings.shares ||= {});
function drawFolders() {
  const names = Object.keys(folders()).sort();
  $("#hFolder").hidden = !names.length;
  $("#hFolder").innerHTML = `<option value="">All folders</option>` + names.map(n => `<option${n === hFolder ? " selected" : ""}>${esc(n)}</option>`).join("");
}
let hFolder = "";
$("#hFolder").onchange = () => { hFolder = $("#hFolder").value; drawHistory(); };
function viewerExtras(run) {
  const on = favs().includes(run.id), link = shares()[run.id];
  return `<div class="row"><button class="btn small ghost" id="vFav">${on ? "★ Favourite" : "☆ Favourite"}</button>
    <select id="vFolder" class="toolsel"><option value="">Add to a folder…</option>${Object.keys(folders()).sort().map(n => `<option${folders()[n].includes(run.id) ? " selected" : ""}>${esc(n)}</option>`).join("")}<option value="+">＋ New folder…</option></select>
    <button class="btn small ghost" id="vShare">${link ? "Copy share link" : "Share link"}</button>${link ? `<button class="btn small ghost" id="vUnshare">Stop sharing</button>` : ""}</div>`;
}
function wireViewerExtras(run) {
  $("#vFav").onclick = () => { const f = favs(), i = f.indexOf(run.id); i >= 0 ? f.splice(i, 1) : f.push(run.id); keep("settings"); $("#vFav").textContent = i >= 0 ? "☆ Favourite" : "★ Favourite"; };
  $("#vFolder").onchange = async e => {
    let name = e.target.value; if (!name) return;
    if (name === "+") {
      const d = await dialog("New folder", `<label class="field">Name<input id="nfName" placeholder="e.g. Summer campaign"></label>`, "Create");
      name = d?.querySelector("#nfName").value.trim();
      if (!name) { e.target.value = ""; return; }
    }
    for (const ids of Object.values(folders())) { const i = ids.indexOf(run.id); if (i >= 0) ids.splice(i, 1); }  // one folder per result
    (folders()[name] ||= []).push(run.id); keep("settings"); drawFolders(); toast(`Added to “${name}”.`); openViewer(run);
  };
  $("#vShare").onclick = async () => {
    try {
      const token = shares()[run.id] || (await api(`/v1/runs/${run.id}/share`, {})).token;
      shares()[run.id] = token; keep("settings");
      const url = `${location.origin}/s.html?t=${token}`;
      await navigator.clipboard.writeText(url).catch(() => {});
      toast("Share link copied. Anyone with it can see this result (not your prompt).", 6000); openViewer(run);
    } catch (e) { toast(e.message); }
  };
  if ($("#vUnshare")) $("#vUnshare").onclick = async () => { try { await api(`/v1/runs/${run.id}/unshare`, {}); delete shares()[run.id]; keep("settings"); toast("Sharing stopped: the link no longer works."); openViewer(run); } catch (e) { toast(e.message); } };
}

// ---------- Images › Sketch: draw it roughly, get a finished picture ----------
(() => {
  const cv = $("#skCv"), ctx = cv.getContext("2d"); let down = false, last = null;
  const clear = () => { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, cv.width, cv.height); };
  clear();
  const at = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
  const line = e => { const p = at(e); ctx.strokeStyle = $("#skErase").checked ? "#fff" : "#111"; ctx.lineWidth = +$("#skSize").value; ctx.lineCap = ctx.lineJoin = "round"; ctx.beginPath(); ctx.moveTo(...(last || p)); ctx.lineTo(...p); ctx.stroke(); last = p; };
  cv.onpointerdown = e => { down = true; last = null; cv.setPointerCapture(e.pointerId); line(e); };
  cv.onpointermove = e => { if (down) line(e); };
  cv.onpointerup = () => { down = false; last = null; };
  $("#skClear").onclick = clear;
  $("#skGo").onclick = async () => {
    const want = $("#skPrompt").value.trim(); if (!want) return toast("Say what the sketch is, e.g. “a red sports car on a mountain road at sunset”.");
    const id = EDITOR(); if (!id) return toast("Sketch isn't available right now.");
    $("#skGo").disabled = true;
    try {
      const sketch = await upload(new File([await new Promise(r => cv.toBlob(r, "image/png"))], "sketch.png", { type: "image/png" }));
      await launch(id, fillFor(await schemaOf(id), { prompt: `Turn this rough sketch into a finished, detailed image: ${want}. Follow the sketch's composition, shapes and layout closely.`, images: [sketch], aspect: "1:1" }), "Sketch");
    } catch (e) { toast(e.message, 6000); }
    $("#skGo").disabled = false;
  };
})();


// ---------- Audio › Voice clone: save a voice from a recording once, then say anything in it ----------
const CLONER = ["fal-ai/qwen-3-tts/clone-voice/1.7b", "fal-ai/qwen-3-tts/clone-voice/0.6b"], SPEAKER = ["fal-ai/qwen-3-tts/text-to-speech/1.7b", "fal-ai/qwen-3-tts/text-to-speech/0.6b"];
const voices = () => (ACC.settings.voices ||= {});
let vcFile = "";
function drawClone() {
  const names = Object.keys(voices()).sort();
  $("#vcSaved").hidden = !names.length;
  $("#vcVoice").innerHTML = names.map(n => `<option>${esc(n)}</option>`).join("");
  $("#vcRec").textContent = vcFile ? "Recording added ✓" : "＋ Add a recording";
}
$("#vcRec").onclick = () => $("#vcFile").click();
$("#vcFile").onchange = async () => { const f = $("#vcFile").files[0]; if (!f) return; try { vcFile = await upload(f); } catch (e) { toast(e.message); } drawClone(); };
$("#vcSave").onclick = async () => {
  const name = $("#vcName").value.trim(), cloner = CLONER.find(byId);
  if (!$("#vcOk").checked) return toast("Voice cloning needs the box ticked: only your own voice, or one you have permission to use.", 7000);
  if (!vcFile) return toast("Add a short, clean recording of the voice first.");
  if (!name) return toast("Give the voice a name.");
  if (!cloner) return toast("Voice cloning isn't available right now.");
  $("#vcSave").disabled = true;
  try {
    const ref = $("#vcRef").value.trim(), run = await launch(cloner, { audio_url: vcFile, ...(ref ? { reference_text: ref } : {}) }, "Voice clone");
    const embedding = JSON.stringify(run.result || {}).match(/https:[^"]+\.safetensors/)?.[0];
    if (run.status !== "done" || !embedding) throw new Error(`The voice couldn't be saved${run.error ? ": " + run.error : ""}. Try a clearer recording.`);
    voices()[name] = { embedding, ref }; keep("settings"); vcFile = ""; $("#vcName").value = ""; drawClone(); $("#vcVoice").value = name;
    toast(`“${name}” is saved. Type what it should say below.`, 6000);
  } catch (e) { toast(e.message, 7000); }
  $("#vcSave").disabled = false;
};
$("#vcSay").onclick = async () => {
  const v = voices()[$("#vcVoice").value], text = $("#vcText").value.trim(), speaker = SPEAKER.find(byId);
  if (!v) return toast("Save a voice first."); if (!text) return toast("Type what it should say.");
  if (!speaker) return toast("This isn't available right now.");
  $("#vcSay").disabled = true;
  try { await launch(speaker, { text, speaker_voice_embedding_file_url: v.embedding, ...(v.ref ? { reference_text: v.ref } : {}) }, "Voice · " + $("#vcVoice").value); }
  catch (e) { toast(e.message, 6000); }
  $("#vcSay").disabled = false;
};
$("#vcDel").onclick = () => { const n = $("#vcVoice").value; if (n && confirm(`Delete the saved voice “${n}”?`)) { delete voices()[n]; keep("settings"); drawClone(); } };

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
  if (run.status === "done" && run.outputs?.length) return `<div class="item" data-id="${esc(run.id)}">${mediaHtml(run.outputs[0])}${run.outputs.length > 1 ? `<span class="count">${run.outputs.length}</span>` : ""}<div class="meta"><span>${label}</span><span${run.upto ? ` title="${UPTO}"` : ""}>${run.upto ? "up to " : ""}${money(run.charged || 0)}</span></div></div>`;
  if (run.status === "done") return `<div class="item"><div class="state">${esc(run.note || byId(run.model)?.name || "Done")}<br><span class="muted">Finished</span></div></div>`;
  if (run.status === "failed" || run.status === "cancelled") return `<div class="item fail"><div class="state">${run.status === "failed" ? "This run didn't work" : "Cancelled"}. You weren't charged.<br><span class="muted">${esc((run.error || "").slice(0, 140))}</span>${run.status === "failed" ? `<span class="tip">${esc(failTip(run.error))}</span>${run.id ? `<button class="btn small ghost" data-ask="${esc(run.id)}">Ask the assistant</button>` : ""}` : ""}</div></div>`;
  return `<div class="item wait"><div class="state">${run.note ? esc(run.note) + "<br>" : ""}${run.queue_position ? `In the queue · ${run.queue_position} ahead` : "Creating…"}</div></div>`;
}
function drawLatest() {
  const items = [...LATEST, ...HIST.filter(h => !LATEST.some(l => l.id === h.id))].slice(0, 12);
  $("#latest").innerHTML = items.length ? items.map(tile).join("") : `<div class="empty">Your creations will appear here.</div>`;
}
let hKind = "";
function drawHistory() {
  const q = $("#hSearch").value.toLowerCase().split(/\s+/).filter(Boolean);
  drawFolders();
  const list = HIST.filter(r => (!hKind || (hKind === "fav" ? favs().includes(r.id) : r.outputs?.length && mediaOf(r.outputs[0]) === hKind)) && (!hFolder || (folders()[hFolder] || []).includes(r.id)) && q.every(w => (promptText(r) + " " + (byId(r.model)?.name || "") + " " + r.model).toLowerCase().includes(w)));
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
    ${appsFor(u).length ? `<select id="vTools" class="toolsel"><option value="">✦ Tools…</option>${appsFor(u).map(a => `<option value="${APPS.indexOf(a)}">${esc(a.label)}</option>`).join("")}</select>` : ""}
    <button class="btn small" id="vAgain">Use these settings</button><button class="btn small" id="vInput">Use as input</button>
    ${kindOf === "video" ? `<button class="btn small" id="vClip">Add to Timeline</button>` : ""}${kindOf === "audio" ? `<button class="btn small" id="vSong">Use as soundtrack</button>` : ""}
    ${kindOf !== "audio" ? `<button class="btn small" id="vScore" title="How well it would stop the scroll, scored by the assistant (about a cent)">Scroll-stop score</button>` : ""}
    ${DRAFTS[run.id] ? `<button class="btn small primary" id="vFinal" title="The full-quality version, same seed">⬆ Make the final version</button>` : ""}
    <button class="btn small" id="vDelete">Delete</button><button class="btn small ghost" id="vClose">Close</button></div>${run.id ? viewerExtras(run) : ""}<div id="vScoreBox" class="scorebox"></div>`;
  $("#viewer").hidden = false;
  $("#vSide").querySelectorAll(".strip button").forEach(b => b.onclick = () => openViewer(run, +b.dataset.i));
  if (run.id) wireViewerExtras(run);
  if ($("#vFinal")) $("#vFinal").onclick = () => { const d = DRAFTS[run.id]; $("#vClose").click(); launch(d.model, d.values, "Final").catch(e => toast(e.message, 6000)); };
  $("#vClose").onclick = () => { $("#viewer").hidden = true; $("#vMedia").innerHTML = ""; };
  $("#vAgain").onclick = () => { $("#vClose").click(); show("create"); C.pick(byId(run.model) || { id: run.model, name: run.model, cat: "", cost: { usd: 0, per: "run" } }, JSON.parse(JSON.stringify(run.input || {}))); };
  $("#vInput").onclick = () => {
    $("#vClose").click(); show("create");
    const k = C.schema && fileKey(C.schema, kindOf);
    if (!k) return toast(`${C.model?.name || "This model"} doesn't take ${kindOf === "image" ? "an image" : "a" + (kindOf === "audio" ? "n audio file" : " video")}. Choose one that does, then try again.`, 6000);
    C.values[k] = C.schema.properties[k].type === "array" ? [...(C.values[k] || []), u] : u; C.redraw(); toast("Added to " + label(k) + ".");
  };
  if ($("#vTools")) $("#vTools").onchange = e => { const a = APPS[+e.target.value]; if (!a) return; if (a[kindOf] !== "score") $("#vClose").click(); useApp(a, u, $("#vScoreBox")); };
  if ($("#vScore")) $("#vScore").onclick = () => scoreIt(u, $("#vScoreBox"));
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
