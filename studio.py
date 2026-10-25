"""Muselight: a local desktop app that runs any image, video or audio model on the cheapest provider you've connected.

Run:  python studio.py        (opens an app window; Ctrl+C in the console to quit)
      python studio.py --selftest

The API key is read from the FAL_KEY environment variable and never stored.
Everything the app makes lives in ./studio_data (outputs, uploads, workflows, history).

Every run is a workflow: a list of steps {model, inputs}. Text values can use
{{name}} placeholders, filled per batch row; {{prev}} is the previous step's first
output URL and {{prev_all}} all of them. Values starting with @ are local files.
"""
import base64, hashlib, json, mimetypes, os, re, sys, threading, time, uuid, urllib.error, urllib.parse, urllib.request, webbrowser, subprocess, shutil
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from fal_run import to_value, output_urls
import agent, providers
from providers import compare

FROZEN = getattr(sys, "frozen", False)  # running as the packaged Muselight.exe
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent  # studio_data lives here (portable)
ASSETS = Path(getattr(sys, "_MEIPASS", ROOT))  # files bundled inside the .exe
DATA = agent.data_dir(ROOT)
providers.init(DATA)
OUT, UPLOADS, WORKFLOWS = DATA / "outputs", DATA / "uploads", DATA / "workflows"
SETTINGS_FILE, HISTORY_FILE = DATA / "settings.json", DATA / "history.jsonl"
PORT = int(os.environ.get("PORT", 8765))
PORT_FILE = DATA / "port.txt"  # tells the connector where the running app is
MEDIA = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

settings = {"own_providers": None, "cheapest": True, "cheaper_popup": True, "brief": "", "brief_on": False, "budget": 0, "confirm_over": 0,
            "rules": {"realism": True, "capture": True, "ugc": True}, "concurrency": 4, "favorites": ["krea/v3/edit", "fal-ai/flux/dev"], "automations": [],
            "credit_suppliers": {}}  # open models on Credits: model -> the supplier the user chose (none = best price)
jobs = {}            # id -> job; the whole app state the UI polls
schemas = {}         # model id -> resolved input schema
cond = threading.Condition()
history_lock = threading.Lock()
page = {"seen": 0.0, "bye": 0.0}  # when the app's page last checked in, and when it said it was closing
running = 0
pool = ThreadPoolExecutor(max_workers=64)  # threads wait at the concurrency gate, so this is only an upper bound


# ---------- fal API ----------

def fal(url, body=None, method=None):
    return providers.call("fal", url, body, method)


def fal_error(code, text):
    return providers.api_error("fal", code, text)


def get_schema(model):
    prov = providers.split(model)[0]
    if prov in ("comfyui", "runpod"):  # your own workflows can change while the app runs
        return providers.schema(model)
    if model not in schemas and prov != "fal":
        schemas[model] = providers.schema(model)
    if model not in schemas:
        schemas[model] = providers.core.fal_schema(model)
    return schemas[model]


MODELS_FILE = DATA / "models.json"
models_lock = threading.Lock()


def refresh_models():
    """Fetch every fal model (about 1,500, ~20s) and cache a compact list."""
    if not models_lock.acquire(blocking=False):
        return  # a refresh is already running
    try:
        out, cursor = [], None
        while True:
            d = fal("https://api.fal.ai/v1/models?limit=100" + (f"&cursor={cursor}" if cursor else ""))
            for m in d["models"]:
                md = m.get("metadata", {})
                out.append({"id": m["endpoint_id"], "name": (md.get("display_name") or "").strip(), "cat": md.get("category", ""),
                            "desc": (md.get("description") or "").strip()[:200], "thumb": md.get("thumbnail_url", ""), "date": md.get("date", "")})
            cursor = d.get("next_cursor")
            if not d.get("has_more"):
                break
        MODELS_FILE.write_text(json.dumps(out), encoding="utf-8")
    finally:
        models_lock.release()


def seed(path):
    """A fresh copy of the app starts from the lists bundled inside it (they refresh in the background when old)."""
    bundled = ASSETS / path.name
    if not path.exists() and bundled.exists() and bundled != path:
        shutil.copy2(bundled, path)  # copy2 keeps the date, so an old list still refreshes


def get_models(force=False):
    seed(MODELS_FILE)
    stale = not MODELS_FILE.exists() or time.time() - MODELS_FILE.stat().st_mtime > 86400
    if force or not MODELS_FILE.exists():
        refresh_models()  # first run: wait for it
    elif stale:
        threading.Thread(target=refresh_models, daemon=True).start()  # serve yesterday's list, refresh behind it
    out = json.loads(MODELS_FILE.read_text(encoding="utf-8")) if MODELS_FILE.exists() else []
    if credits_mode():
        # the models Muselight Credits sells, under their usual ids (so saved workflows keep working), at the price you'd pay
        kin = {m["id"].split(":", 1)[1]: m for m in provider_models("muselight", force)}
        if kin:
            out = [dict(m, cost=kin[m["id"]]["cost"], price=kin[m["id"]].get("price", "")) for m in out if m["id"] in kin]
        return with_keys(out)
    for prov in providers.MODULES:
        if providers.has_key(prov):
            out += provider_models(prov, force)
    return with_keys(out)


def with_keys(items):
    """Tag each model with its identity across providers (the picker shows one row per identity) and fal's list prices."""
    load_fal_costs()
    out = []
    for m in items:
        prov, bare = providers.split(m["id"])
        m = dict(m, key=compare.canon(bare, m.get("cat", "")) or m["id"])
        if prov == "fal" and not m.get("cost") and fal_costs.get(m["id"]):
            m["cost"] = fal_costs[m["id"]]
        out.append(m)
    return out


offline_tried = set()


def all_models(force=False):
    """Every provider's models for the model picker (one row per model): ones you can't run on any connected provider carry off=True."""
    fal_on = providers.has_key("fal")
    out = [m if fal_on or providers.split(m["id"])[0] != "fal" else dict(m, off=True) for m in get_models(force)]
    for prov in providers.MODULES:
        if providers.has_key(prov) or prov == "comfyui":
            continue
        f = DATA / f"models_{prov}.v2.json"
        if f.exists():
            out += [dict(m, off=True) for m in json.loads(f.read_text(encoding="utf-8"))]
        elif prov not in offline_tried:  # first time: fetch its public list in the background (needs-a-key providers just fail quietly)
            offline_tried.add(prov)
            threading.Thread(target=provider_models, args=(prov,), daemon=True).start()
    return with_keys(out)


# catalogue caches carry a version: bump it when the fields saved per model change (v2 added prices)
def provider_models(prov, force=False):
    """Another provider's models, cached for a day like fal's. A failed refresh keeps the old list."""
    if prov == "comfyui":  # your own workflows: always the current folder
        try:
            return providers.list_models(prov)
        except Exception:
            return []
    f = DATA / f"models_{prov}.v2.json"

    def refresh():
        try:
            f.write_text(json.dumps(providers.list_models(prov)), encoding="utf-8")
        except Exception as e:
            print(f"couldn't list {prov} models:", e)
    if force or not f.exists():
        refresh()
    elif time.time() - f.stat().st_mtime > 86400:
        threading.Thread(target=refresh, daemon=True).start()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


PARAMS_FILE = DATA / "params.json"
params_lock = threading.Lock()


def build_params():
    """Collect every input parameter used by any fal model: name -> {count, prop} (one schema fetch per model)."""
    if not params_lock.acquire(blocking=False):
        return
    try:
        def one(m):
            try:
                return get_schema(m["id"])
            except Exception:
                return None
        out = {}
        with ThreadPoolExecutor(16) as ex:
            for sch in ex.map(one, get_models()):
                for k, p in ((sch or {}).get("properties") or {}).items():
                    out.setdefault(k, {"count": 0, "prop": p})["count"] += 1
        PARAMS_FILE.write_text(json.dumps(out), encoding="utf-8")
    finally:
        params_lock.release()


def get_params():
    seed(PARAMS_FILE)
    if not PARAMS_FILE.exists():
        threading.Thread(target=build_params, daemon=True).start()
        return {"building": True}
    if time.time() - PARAMS_FILE.stat().st_mtime > 7 * 86400:
        threading.Thread(target=build_params, daemon=True).start()
    return json.loads(PARAMS_FILE.read_text(encoding="utf-8"))


# ---------- connections ----------
# Keys are kept in Windows Credential Manager (encrypted, per Windows user), never in files, and never sent back to the page.
# Addresses aren't secret, so they live in settings.json. Either way they're applied to os.environ, where the code reads them.
VAULT = "Fal Studio"  # the app's old name; kept so keys saved before the rename still load
CONNECTIONS = [
    {"name": "FAL_KEY", "label": "fal.ai", "group": providers.GROUPS["market"], "kind": "key", "link": "https://fal.ai/dashboard/keys",
     "help": "The biggest catalogue (about 1,500 models). Create a key in your fal dashboard."},
    {"name": "FAL_ADMIN_KEY", "label": "fal.ai · admin key (optional)", "group": providers.GROUPS["market"], "kind": "key", "link": "https://fal.ai/dashboard/keys",
     "help": "Only for showing exactly what each fal run cost (fal shares billing records with admin keys only). Runs still use your normal key."},
    {"name": "OPENROUTER_API_KEY", "label": "OpenRouter · free models", "group": "Free assistants", "kind": "key", "provider": "openrouter",
     "link": "https://openrouter.ai/settings/keys", "help": "Free account, no card needed. About 50 free requests a day."},
    {"name": "OLLAMA_URL", "label": "Ollama", "group": "Free assistants", "kind": "url", "default": "http://127.0.0.1:11434", "provider": "ollama",
     "link": "https://ollama.com/download", "help": "Runs models on your PC. Install it, run `ollama pull qwen3`, and keep it open."},
    {"name": "LMSTUDIO_URL", "label": "LM Studio", "group": "Free assistants", "kind": "url", "default": "http://127.0.0.1:1234", "provider": "lmstudio",
     "link": "https://lmstudio.ai", "help": "Runs models on your PC. Load a model with tool use, then Developer → Start Server."},
    {"name": "ANTHROPIC_API_KEY", "label": "Claude API", "group": "Your own API keys", "kind": "key", "provider": "claude",
     "link": "https://console.anthropic.com/settings/keys", "help": "Paid per use."},
    {"name": "OPENAI_API_KEY", "label": "ChatGPT · OpenAI API", "group": "Your own API keys", "kind": "key", "provider": "chatgpt",
     "link": "https://platform.openai.com/api-keys", "help": "Paid per use. A ChatGPT subscription doesn't include API access. The same key also runs OpenAI's image models."},
    {"name": "XAI_API_KEY", "label": "Grok · xAI API", "group": "Your own API keys", "kind": "key", "provider": "grok",
     "link": "https://console.x.ai", "help": "Paid per use. New accounts sometimes get promotional credits. The same key also runs Grok Imagine images and video."},
    {"name": "VENICE_API_KEY", "label": "Venice API", "group": "Your own API keys", "kind": "key", "provider": "venice",
     "link": "https://venice.ai/settings/api", "help": "Venice Pro includes a one-time API credit."},
    {"name": "OPENCLAW_URL", "label": "OpenClaw gateway address", "group": "Your own API keys", "kind": "url", "default": "http://127.0.0.1:18789",
     "provider": "openclaw", "link": "https://docs.openclaw.ai/gateway/openai-http-api", "help": "Turn on the gateway's chat completions endpoint first."},
    {"name": "OPENCLAW_GATEWAY_TOKEN", "label": "OpenClaw gateway token", "group": "Your own API keys", "kind": "key", "provider": "openclaw",
     "link": "https://docs.openclaw.ai/gateway/openai-http-api", "help": "The gateway's auth token (gateway.auth.token)."},
    {"name": "NOVITA_API_KEY", "label": "Novita AI", "group": "Your own API keys", "kind": "key", "provider": "novita",
     "link": "https://novita.ai/settings/key-management", "help": "Low-cost open models (Qwen, DeepSeek, Llama) for the assistant."},
    {"name": "RUNPOD_LLM_ENDPOINT", "label": "RunPod · your own assistant model", "group": "Your own API keys", "kind": "text", "provider": "runpod",
     "link": "https://console.runpod.io/serverless", "help": "Easiest: GPUs → Assistant model → Deploy, which fills this in. Or paste the id of a vLLM endpoint."},
]
for c in providers.connections({c["name"] for c in CONNECTIONS}):  # every other provider's key, grouped
    if c["provider_id"] in agent.PROVIDERS:
        c["provider"] = c["provider_id"]  # this key also runs the assistant
    CONNECTIONS.insert(1 + sum(1 for x in CONNECTIONS if x.get("provider_id")), c)
CONN = {c["name"]: c for c in CONNECTIONS}
saved_in_app = set()


def _vault():
    try:
        import keyring
        return keyring
    except ImportError:
        raise RuntimeError("Saving keys needs the keyring package: run `python -m pip install keyring`, then restart Muselight.")


def load_connections():
    for c in CONNECTIONS:
        try:
            v = settings.get("urls", {}).get(c["name"]) if c["kind"] != "key" else _vault().get_password(VAULT, c["name"])
        except Exception as e:
            print("couldn't read saved connection", c["name"], e)
            continue
        if v:  # a value saved in the app wins over an older Windows variable
            os.environ[c["name"]] = v
            saved_in_app.add(c["name"])


def connection_list():
    out = []
    for c in CONNECTIONS:
        v = os.environ.get(c["name"], "")
        item = {k: c.get(k) for k in ("name", "label", "group", "kind", "link", "help", "provider", "default")}
        item.update(set=bool(v), source="app" if c["name"] in saved_in_app else ("windows" if v else ""))
        if c["kind"] != "key":
            item["value"] = v
        elif v:
            item["preview"] = "…" + v[-4:] if len(v) > 8 else "saved"
        out.append(item)
    return out


def save_connection(name, value):
    c = CONN.get(name)
    if not c:
        raise RuntimeError("Unknown connection")
    value = (value or "").strip()
    if c["kind"] != "key":
        if c["kind"] == "url" and value and not re.match(r"^https?://[\w.\-]+(:\d+)?/?$", value):
            raise RuntimeError("Use an address like " + (c.get("default") or "http://127.0.0.1:11434"))
        urls = settings.setdefault("urls", {})
        urls.pop(name, None) if not value else urls.__setitem__(name, value.rstrip("/"))
        save_settings()
    elif value:
        _vault().set_password(VAULT, name, value)
    elif name in saved_in_app:
        try:
            _vault().delete_password(VAULT, name)
        except Exception:
            pass
    if value:
        os.environ[name] = value.rstrip("/") if c["kind"] == "url" else value
        saved_in_app.add(name)
    elif name in saved_in_app:
        os.environ.pop(name, None)
        saved_in_app.discard(name)
    if providers.provider_of_key(name):
        (DATA / f"models_{providers.provider_of_key(name)}.v2.json").unlink(missing_ok=True)  # changed key: fetch that provider's models fresh


def credits_status():
    """Muselight Credits for the Credits window: whether the service is live, and this PC's account and balance."""
    kc = providers.MODULES["muselight"]
    out = {"live": bool(kc.url()), "signed_in": bool(providers.core.key("MUSELIGHT_TOKEN"))}
    if out["live"] and out["signed_in"]:
        try:
            out.update(kc.balance())
        except Exception as e:
            out["error"] = str(e)
    return out


def credits_action(action, b):
    kc = providers.MODULES["muselight"]
    if not kc.url():
        raise RuntimeError("Muselight Credits isn't open yet.")
    if action == "join":
        save_connection("MUSELIGHT_TOKEN", kc.join(b.get("accept_terms")))
    elif action == "signin":  # the sign-in code from another PC
        old = os.environ.get("MUSELIGHT_TOKEN", "")
        os.environ["MUSELIGHT_TOKEN"] = (b.get("code") or "").strip()
        try:
            kc.balance()
        except Exception:
            os.environ["MUSELIGHT_TOKEN"] = old
            raise RuntimeError("That sign-in code wasn't recognised.")
        save_connection("MUSELIGHT_TOKEN", b["code"])
    elif action == "topup":
        webbrowser.open(kc.topup(b.get("amount")))  # Paddle's checkout, in the normal browser
    elif action == "code":
        return {"code": providers.core.key("MUSELIGHT_TOKEN")}
    elif action == "prices":
        return {"models": provider_models("muselight", force=bool(b.get("fresh")))}
    else:
        raise RuntimeError("Unknown action")
    return credits_status()


def test_connection(name):
    c = CONN[name]
    prov = providers.provider_of_key(name)
    if prov:
        if not os.environ.get(name) and c["kind"] == "key":
            return {"ok": False, "message": "No key saved yet"}
        if not providers.has_key(prov):
            return {"ok": False, "message": "Saved. Fill in the other " + providers.label(prov) + " box too, then Test."}
        try:
            msg = providers.test(prov)
            provider_models(prov, force=True)  # its models show up in the pickers straight away
            return {"ok": True, "message": msg}
        except Exception as e:
            return {"ok": False, "message": str(e)[:200]}
    if name == "FAL_ADMIN_KEY":
        if not os.environ.get(name):
            return {"ok": False, "message": "No key saved yet"}
        try:
            req = urllib.request.Request("https://api.fal.ai/v1/models/billing-events?limit=1", headers={"Authorization": "Key " + os.environ.get(name, ""), "User-Agent": providers.core.UA})
            urllib.request.urlopen(req, timeout=20).close()
            return {"ok": True, "message": "Admin key works: fal runs will show what they actually cost"}
        except urllib.error.HTTPError as e:
            return {"ok": False, "message": "That key can't read billing records. Create one with the Admin scope." if e.code in (401, 403) else f"fal error {e.code}"}
        except Exception as e:
            return {"ok": False, "message": f"Couldn't reach fal: {str(e)[:150]}"}
    if name == "FAL_KEY":
        if not os.environ.get("FAL_KEY"):
            return {"ok": False, "message": "No key saved yet"}
        try:
            fal("https://api.fal.ai/v1/models?limit=1")
            return {"ok": True, "message": "Connected to fal"}
        except Exception as e:
            return {"ok": False, "message": "fal rejected this key" if "401" in str(e) or "403" in str(e) else str(e)[:200]}
    try:
        if c["provider"] == "openrouter":  # its model list is public, so check the key itself
            agent._http("https://openrouter.ai/api/v1/key", headers=agent._openai_target("openrouter")[1], timeout=20)
        n = len(agent.list_models(c["provider"]))
        return {"ok": True, "message": f"Connected · {n} model{'s' if n != 1 else ''} available"}
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg:
            msg = "The key was rejected. Check it was copied in full."
        elif "refused" in msg.lower() or "urlopen error" in msg.lower() or "timed out" in msg.lower():
            msg = "Nothing answered at that address. Is the app running?"
        return {"ok": False, "message": msg[:200]}


# ---------- price comparison ----------
# The same model is often on several providers. Each run goes to the cheapest connected one (when "Cheapest" is on),
# with its settings translated; providers you haven't connected but that list a lower price are mentioned.
prices = {"t": 0.0, "index": {}, "items": {}}
fal_costs = {}  # fal endpoint id -> cost (from fal's pricing API, needs the fal key)


def price_catalog():
    """Every model the app knows, with list prices where published: fal, connected providers, and every other provider's
    public catalogue it has fetched (so "the same model" can be found anywhere). Rebuilt every 10 minutes."""
    if time.time() - prices["t"] < 600:
        return prices
    seed(MODELS_FILE)
    items = {m["id"]: dict(m, prov="fal") for m in (json.loads(MODELS_FILE.read_text(encoding="utf-8")) if MODELS_FILE.exists() else [])}
    for prov in providers.MODULES:
        if not providers.has_key(prov) and not (DATA / f"models_{prov}.v2.json").exists():
            if prov in compare.PUBLIC_PRICES:
                threading.Thread(target=provider_models, args=(prov,), daemon=True).start()  # first time: fetch in the background
            continue
        for m in provider_models(prov):
            items[m["id"]] = dict(m, prov=prov)
    index = {}
    for mid, m in items.items():
        key = compare.canon(providers.split(mid)[1], m.get("cat", ""))
        if key:
            index.setdefault(key, []).append(mid)
    prices.update(t=time.time(), index=index, items=items)
    return prices


FAL_PRICES_FILE = DATA / "fal_prices.json"
fal_prices_lock = threading.Lock()


def load_fal_costs():
    """fal list prices from the daily file; refreshes it in the background when it's old (needs the fal key)."""
    if not fal_costs and FAL_PRICES_FILE.exists():
        try:
            fal_costs.update(json.loads(FAL_PRICES_FILE.read_text(encoding="utf-8")))
        except ValueError:
            pass
    old = not FAL_PRICES_FILE.exists() or time.time() - FAL_PRICES_FILE.stat().st_mtime > 86400
    if old and os.environ.get("FAL_KEY") and fal_prices_lock.acquire(blocking=False):
        def refresh():
            try:
                ids = [m["id"] for m in json.loads(MODELS_FILE.read_text(encoding="utf-8"))] if MODELS_FILE.exists() else []
                for x in ids:
                    fal_costs.pop(x, None)
                fetch_fal_costs(ids)
                FAL_PRICES_FILE.write_text(json.dumps({k: v for k, v in fal_costs.items() if v}), encoding="utf-8")
            finally:
                fal_prices_lock.release()
        threading.Thread(target=refresh, daemon=True).start()


def fetch_fal_costs(ids):
    """fal list prices, 40 models per request, paced and retried because fal limits how fast this can be called."""
    ids = [i for i in ids if i not in fal_costs]
    if not ids or not os.environ.get("FAL_KEY"):
        return
    for i in range(0, len(ids), 40):
        chunk, rows = ids[i:i + 40], None
        for attempt in range(5):
            try:
                rows = fal("https://api.fal.ai/v1/models/pricing?endpoint_id=" + ",".join(urllib.parse.quote(x, safe="/") for x in chunk)).get("prices", [])
                break
            except Exception as e:
                if "limiting" not in str(e):
                    break
                time.sleep(3 * (attempt + 1))
        if rows is None:
            continue  # couldn't ask: leave these unknown so they're tried again later
        for x in chunk:
            fal_costs[x] = None
        for r in rows:
            if providers.core.fal_price(r):
                fal_costs[r["endpoint_id"]] = providers.core.fal_price(r)
        if len(ids) > 40:
            time.sleep(1.5)


def cost_of(mid):
    item = prices["items"].get(mid) or {}
    if item.get("cost"):
        return item["cost"]
    prov, bare = providers.split(mid)
    if prov == "fal":
        fetch_fal_costs([mid])
        return fal_costs.get(mid)
    m = providers.MODULES[prov]
    if hasattr(m, "cost") and "cost_lazy" not in item:
        try:
            item["cost_lazy"] = m.cost(bare)
        except Exception:
            item["cost_lazy"] = None
    return item.get("cost_lazy")


def price_options(model, body, quotes=0):
    """Every provider's price for this run, as accurate as can be had: the provider's own quote for these exact settings
    (quotes = how many connected providers to ask), else what your past runs there actually cost, else the list price."""
    cat = price_catalog()
    me = cat["items"].get(model) or {}
    key = compare.canon(providers.split(model)[1], me.get("cat", ""))
    fetch_fal_costs([m for m in cat["index"].get(key, [model]) if providers.split(m)[0] == "fal"])
    rows, src = compare.options(model, body, cat["index"], cat["items"].get, get_schema, cost_of, providers.has_key)
    for r in rows:
        r["basis"] = "list" if r["est"] is not None else None
        m = measured(r["model"])
        if m and r.get("units"):
            r.update(est=m["per_unit"] * r["units"], basis="measured", runs=m["n"])
    asked = [r for r in rows if r["model"] == model]
    quotable = [r for r in asked + [r for r in rows if r["model"] != model]
                if r["connected"] and hasattr(providers.MODULES.get(providers.split(r["model"])[0]), "quote")]
    asks = quotable[:quotes]
    with ThreadPoolExecutor(max(1, len(asks))) as ex:  # each provider can take a few seconds; ask them all at once
        got = list(ex.map(lambda r: provider_quote(r["model"], body if r["model"] == model else None, src, body), asks))
    for r, (q, why) in zip(asks, got):
        if q is not None:
            r.update(est=q, basis="quote")
        elif why:
            r["quote_error"] = why
    for r in rows:
        r["per_unit"] = r["est"] / r["units"] if r["est"] is not None and r.get("units") else r.get("per_unit")
    rows.sort(key=lambda r: (r["est"] is None, r["est"] or 0))
    return rows, src


quotes = {}  # (model, settings) -> (time, price)


def provider_quote(model, own_body, src_schema, body):
    """The provider's own price for exactly these settings (files included). Returns (usd or None, why not)."""
    prov, bare = providers.split(model)
    if own_body is None:
        own_body, why = compare.translate(body, src_schema, get_schema(model))
        if own_body is None:
            return None, why
    key = json.dumps([model, own_body], sort_keys=True, default=str)
    if key in quotes and time.time() - quotes[key][0] < 600:
        return quotes[key][1], None
    try:
        b = clean(dict(own_body))
        try:
            b = fit_to_schema(b, get_schema(model))
        except Exception:
            pass
        usd = providers.MODULES[prov].quote(bare, local_files(b, prov))
        usd = float(usd) if usd is not None else None
    except Exception as e:
        return None, str(e)[:160]
    quotes[key] = (time.time(), usd)
    return usd, None


# ---------- what runs actually cost ----------
# Providers that report the charge (Runware, Segmind, DeepInfra, RunPod, and fal's billing records) teach the app real prices:
# a model you've run before is priced from what it actually cost per second / per image, not from its list price.
COSTS_FILE = DATA / "costs.jsonl"
cost_lock = threading.RLock()
spent = {}  # model -> [cost per unit, …]


def measured(model):
    with cost_lock:
        if not spent:
            for line in COSTS_FILE.read_text(encoding="utf-8").splitlines() if COSTS_FILE.exists() else []:
                try:
                    c = json.loads(line)
                    spent.setdefault(c["model"], []).append(c["per_unit"])
                except (ValueError, KeyError):
                    pass
            spent.setdefault("", [])  # loaded (even if empty)
    runs = spent.get(model) or []
    return {"per_unit": sum(runs[-10:]) / len(runs[-10:]), "n": len(runs)} if runs else None


def add_charge(job, model, body, usd):
    """Record what a step really cost: on the run (shown on its card) and in the price history."""
    if usd is None or usd <= 0:
        return
    job["cost"] = round((job.get("cost") or 0) + usd, 6)
    key = compare.canon(providers.split(model)[1], (prices["items"].get(model) or {}).get("cat", "")) or ""
    r = compare.roles(body)
    units = (compare._num(r.get("duration")) or 5) if "~video" in key else max(1, int(compare._num(r.get("count")) or 1))
    rec = {"model": model, "usd": usd, "units": units, "per_unit": usd / units, "t": time.time()}
    with cost_lock:
        measured(model)
        spent.setdefault(model, []).append(rec["per_unit"])
        with open(COSTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def charge(job, model, body, result):
    prov = providers.split(model)[0]
    if prov == "fal":
        rid, admin = job.get("request_id"), os.environ.get("FAL_ADMIN_KEY")
        if rid and admin:
            def later():  # fal's billing record appears shortly after the run (readable with an admin key only)
                for wait in (20, 60, 180):
                    time.sleep(wait)
                    try:
                        req = urllib.request.Request("https://api.fal.ai/v1/models/billing-events?request_id=" + urllib.parse.quote(rid),
                                                     headers={"Authorization": "Key " + admin, "User-Agent": providers.core.UA})
                        with urllib.request.urlopen(req, timeout=60) as r:
                            ev = json.load(r).get("billing_events") or []
                    except urllib.error.HTTPError as e:
                        if e.code in (401, 403):
                            return  # not an admin key
                        continue
                    except Exception:
                        continue
                    if ev:
                        add_charge(job, model, body, sum(e.get("cost_total") or 0 for e in ev))
                        rewrite_history()
                        return
            threading.Thread(target=later, daemon=True).start()
        return
    m = providers.MODULES.get(prov)
    if hasattr(m, "charged"):
        try:
            add_charge(job, model, body, m.charged(result))
        except Exception as e:
            print("couldn't read the charge:", e)


def credits_mode():
    """Muselight Credits is the default: every run goes through it unless the user turns on their own provider accounts
    (Connections). Left unset, it follows whether the Credits service is live, so an app shipped before it opens still works;
    a choice the user made either way is kept."""
    own = settings.get("own_providers")
    return bool(providers.MODULES["muselight"].url()) if own is None else not own


def apply_mode():
    providers.ONLY = {"muselight"} if credits_mode() else None
    prices["t"] = 0  # which providers count as connected changed: rebuild the price catalogue


def route(model, body):
    """Where this run should go: (model, settings, note). The note says what it costs and what might be cheaper elsewhere."""
    connected = providers.has_key(providers.split(model)[0])
    switch = settings.get("cheapest", True) or not connected
    rows, src = price_options(model, body, quotes=4 if switch else 0)  # exact quotes from the likeliest providers first
    pick = compare.choose(model, body, rows, src, get_schema) if switch else None
    used, used_body = (pick[0], pick[1]) if pick else (model, body)
    est = lambda m: next((r["est"] for r in rows if r["model"] == m), None)
    cheaper = [r for r in rows if not r["connected"] and r["est"] is not None and est(used) is not None and r["est"] < est(used) * 0.95
               and not credits_mode()]  # on Credits, other providers' prices are only shown to people who've chosen their own accounts
    runnable = providers.has_key(providers.split(used)[0])  # on Credits, a model it doesn't sell has no price for this user
    note = {"asked": model, "used": used, "provider": providers.label(providers.split(used)[0]), "est": est(used) if runnable or not credits_mode() else None,
            "asked_est": est(model),
            "cheaper": [{"provider": providers.label(r["provider"]), "model": r["model"], "est": r["est"]} for r in cheaper[:3]]}
    return used, used_body, note


def price_view(model, inputs, exact=False):
    """For the page: this model on every provider, priced for these settings (with exact quotes when asked), and where it will run."""
    rows, src = price_options(model, inputs, quotes=99 if exact else 0)
    connected = providers.has_key(providers.split(model)[0])
    pick = compare.choose(model, inputs, rows, src, get_schema) if settings.get("cheapest", True) or not connected else None
    used = pick[0] if pick else model
    suppliers = None
    if credits_mode():
        rows = [r for r in rows if r["model"] == used]
        prov, bare = providers.split(used)
        if prov == "muselight" and providers.has_key(prov):
            plain = {k: v for k, v in inputs.items() if not (isinstance(v, str) and v.startswith("@"))}  # files don't change who can run it
            chosen = settings["credit_suppliers"].get(bare, "")
            try:
                suppliers = dict(providers.MODULES[prov].options(bare, plain), chosen=chosen, model=bare)
            except Exception as e:
                if chosen:  # the chosen supplier can't take these settings: say so, with everyone else's prices
                    try:
                        suppliers = dict(providers.MODULES[prov].options(bare, plain, chosen=False), chosen=chosen, model=bare, error=str(e)[:200])
                    except Exception:
                        pass
    return {"cheapest_on": settings.get("cheapest", True), "used": used, "suppliers": suppliers,
            "rows": [{"model": r["model"], "provider": providers.label(r["provider"]), "connected": r["connected"], "est": r["est"], "cost": r.get("cost"), "per_unit": r.get("per_unit"), "metric": r.get("metric"),
                      "basis": r.get("basis"), "runs": r.get("runs"), "quote_error": r.get("quote_error"),
                      "can_quote": r["connected"] and hasattr(providers.MODULES.get(providers.split(r["model"])[0]), "quote"),
                      "why_not": r.get("why_not"), "used": r["model"] == used, "asked": r["model"] == model} for r in rows]}


SPEND_FILE = DATA / "spend.jsonl"  # one line per finished run: what it cost (charged, or estimated when the provider doesn't say)
spend_lock = threading.Lock()
spend_cache = {"t": 0.0, "usd": 0.0}


def month_spend():
    """Spent since the 1st of this month, in USD."""
    if time.time() - spend_cache["t"] < 10:
        return spend_cache["usd"]
    start = time.mktime(time.strptime(time.strftime("%Y-%m-01"), "%Y-%m-%d"))
    total = 0.0
    with spend_lock:
        for line in SPEND_FILE.read_text(encoding="utf-8").splitlines() if SPEND_FILE.exists() else []:
            try:
                r = json.loads(line)
                total += r["usd"] if r["t"] >= start else 0
            except (ValueError, KeyError):
                pass
    spend_cache.update(t=time.time(), usd=total)
    return total


def log_spend(job):
    usd = job.get("cost") if job.get("cost") is not None else job.get("est")
    if usd:
        with spend_lock, open(SPEND_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "usd": usd, "charged": job.get("cost") is not None, "job": job["id"]}) + "\n")
        spend_cache["t"] = 0


def over_budget(extra=0.0):
    """None, or why a run would break the monthly budget."""
    budget = float(settings.get("budget") or 0)
    spent = month_spend()
    if budget and spent + extra > budget:
        return f"This would go over your monthly budget: ${spent:.2f} of ${budget:.2f} spent" + (f", and this run is about ${extra:.2f}." if extra else ".")
    return None


def precheck(steps, rows, values, repeat=1):
    """Before a run: where each model will run, whether an unconnected provider lists it cheaper, and what it all costs."""
    out, total = [], 0.0
    try:
        all_rows = [v | r for v in value_rows(values, steps) for r in (rows or [{}])] or [{}]
    except Exception:
        all_rows = [{}]
    n = len(all_rows) * max(1, int(repeat or 1))
    for step in steps:
        try:
            used, _, note = route(step["model"], clean(fill(step["inputs"], all_rows[0])))
        except Exception:
            continue
        total += (note["est"] or 0) * n
        if note["cheaper"]:
            name = (prices["items"].get(step["model"]) or {}).get("name") or step["model"]
            out.append({"model": name, "provider": note["provider"], "est": note["est"], "cheaper": note["cheaper"]})
    return {"cheaper": out, "est": total, "runs": n, "month": month_spend(), "budget": float(settings.get("budget") or 0),
            "confirm_over": float(settings.get("confirm_over") or 0), "over": over_budget(total)}


# ---------- templating ----------

def fill(value, vars):
    """Replace {{name}} placeholders. A value that is only a placeholder takes the variable's raw value (e.g. a list)."""
    if isinstance(value, str):
        m = re.fullmatch(r"\{\{(\w+)\}\}", value.strip())
        if m and m.group(1) in vars:
            return vars[m.group(1)]
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(vars.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        out = []
        for v in value:
            f = fill(v, vars)
            out.extend(f) if isinstance(f, list) and not isinstance(v, list) else out.append(f)
        return out
    if isinstance(value, dict):
        return {k: fill(v, vars) for k, v in value.items()}
    return value


def local_files(value, prov="fal"):
    """Turn '@path' strings into data URIs (or uploaded links, for providers that want those). Relative paths are inside studio_data."""
    if isinstance(value, str) and value.startswith("@") and re.search(r"\.\w{2,5}$", value):
        p = Path(value[1:])
        p = p if p.is_absolute() else DATA / p
        if not p.is_file():
            raise RuntimeError(f"File not found: {p}")
        return fal_file(p) if prov == "fal" else providers.local_value(prov, p)
    if isinstance(value, list):
        return [local_files(v, prov) for v in value]
    if isinstance(value, dict):
        return {k: local_files(v, prov) for k, v in value.items()}
    return value


fal_uploaded = {}  # (file, size, modified) -> link on fal's storage


def fal_file(p):
    """A local file for fal: small ones inline, bigger ones (videos, audio) uploaded to fal's storage once and linked."""
    st = p.stat()
    if st.st_size < 3_000_000 and p.suffix.lower() != ".zip":
        return to_value(f"@{p}")
    key = (str(p), st.st_size, st.st_mtime)
    if key not in fal_uploaded:
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        try:
            up = fal("https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3", {"content_type": mime, "file_name": p.name})
            req = urllib.request.Request(up["upload_url"], data=p.read_bytes(), method="PUT", headers={"Content-Type": mime})
            urllib.request.urlopen(req, timeout=600).close()
            fal_uploaded[key] = up["file_url"]
        except Exception as e:
            print("fal upload failed, sending inline:", e)
            return to_value(f"@{p}")
    return fal_uploaded[key]


def import_product(url):
    """Name, description and photos from a shop page, the photos saved as uploads."""
    get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=providers.core.BROWSER_HEADERS), timeout=30)
    name, desc, imgs = providers.core.read_product(url, get)
    saved = []
    for i, src in enumerate(imgs):
        if len(saved) >= 5:
            break
        try:
            with get(src) as r:
                ext = mimetypes.guess_extension(r.headers.get_content_type() or "") or ".jpg"
                data = r.read(20_000_000)
            if len(data) < 5000:
                continue  # icons and tracking pixels
            f = f"{uuid.uuid4().hex[:8]}_{safe_name(name or 'product')[:40].replace(' ', '-')}-{i + 1}{'.jpg' if ext in ('.jpe', '.jfif') else ext}"
            (UPLOADS / f).write_bytes(data)
            saved.append(f"@uploads/{f}")
        except Exception:
            continue
    if not name and not saved:
        raise RuntimeError("Couldn't read a product from that page. Some shops block apps; upload the photos instead.")
    return {"name": name, "description": desc, "images": saved}


def producer(messages, product, provider=None, model=None):
    """One turn of the ad producer: it asks a few questions, then writes the campaign brief as JSON."""
    system = ("You are a sharp ad producer at a performance-marketing studio. Help the user turn their product into an ad campaign. "
              "Ask ONE short question at a time (at most four in total) about whatever is still unclear: what makes the product special, who it's for, "
              "the goal or offer, the hook, and video or still (and which platform). Suggest options when it helps. Be brief and friendly. "
              "When you know enough, or the user says go, reply with one sentence followed by a line starting with BRIEF: and then JSON only: "
              '{"name": str, "audience": str, "brief": str, "headline": str, "hook": str, '
              '"modes": [some of "product","lifestyle","ugc","ad","poster","marketplace","unboxing","model"], '
              '"formats": [some of "1:1","4:5","9:16","16:9"], "video": true/false, '
              '"concepts": {"<mode>": ["a vivid, specific image prompt that refers to the product as the product in the reference images", ...]}, '
              '"script": "for video ads, a short shot list with the hook in the first second"}.')
    known = f"Product so far: name={product.get('name') or '?'}; details={product.get('brief') or '?'}; photos={product.get('photos', 0)}."
    convo = "\n".join(f"{'User' if m.get('role') == 'user' else 'Producer'}: {m.get('content', '')}" for m in messages[-20:])
    return agent.complete(provider, model, system, f"{known}\n\n{convo}\nProducer:")


def score_media(images, kind, context, provider=None, model=None):
    """How well a result would stop the scroll: the assistant looks at it (for a video, its first frames) and scores it."""
    if not images:
        raise RuntimeError("Nothing to look at")
    what = "the first seconds of a short video (frames in order)" if kind == "video" else "an image for social media or an ad"
    text = agent.complete(provider, model, "You are a senior social media creative strategist who scores content for scroll-stopping power. Reply with only JSON.",
                          f"Score {what}. Context from the creator: {context or 'none'}.\n"
                          'Reply as JSON: {"hook": 0-100 (would it stop the scroll in the first second), "clarity": 0-100 (is the subject and message instantly clear), '
                          '"emotion": 0-100, "composition": 0-100 (framing, contrast, focal point, readable on a phone), "platform_fit": 0-100 (native to TikTok/Reels/Feed), '
                          '"overall": 0-100, "verdict": one sentence, "strengths": [up to 3 short points], "fixes": [up to 4 specific, actionable changes]}', images=images)
    a, b = text.find("{"), text.rfind("}")
    if a < 0:
        raise RuntimeError("The assistant didn't return a score. Try again, or pick an assistant model that can see images.")
    return json.loads(text[a:b + 1])


def clean(inputs):
    return {k: v for k, v in inputs.items() if v is not None and v != "" and v != []}


def fit_to_schema(body, schema):
    """Lists sent to a field that takes fewer items keep the first ones, in order."""
    props = schema.get("properties", {})
    for k, v in list(body.items()):
        p = props.get(k)
        if not p or not isinstance(v, list):
            continue
        options = [p] + p.get("anyOf", [])
        arr = next((o for o in options if o.get("type") == "array"), None)
        if arr is not None:
            if arr.get("maxItems") or p.get("maxItems"):
                body[k] = v[: arr.get("maxItems") or p.get("maxItems")]
        elif any(o.get("type") in ("string", "integer", "number", "boolean") for o in options):
            body[k] = v[0]  # single-value field fed a list
    return body


# ---------- @mentions: "@hero" in a prompt means the file hero.png ----------
# Before a run, each mention is matched to a file (one already in the run's settings, else an upload) and marked as @[path];
# a mentioned file the run doesn't include yet is added to the model's image/video/audio input. Just before sending, each mark
# becomes the reference the receiving model understands, numbered by where that file really sits in what is sent:
# "Image 2" for most, "@Image2" for Kling and Grok, "[@reference_image_2]" for Vidu (read from the model's own prompt help).
MENTION = re.compile(r"(?<![\w@/.\\])@([A-Za-z0-9][\w\-]*[A-Za-z0-9]|[A-Za-z0-9])")
MARK = re.compile(r"@\[([^\]]+)\]")
KINDS = {"video": (".mp4", ".webm", ".mov", ".m4v"), "audio": (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")}


# Written for this app. Each fires only when the prompt uses its words, so stylised work is left alone.
_REAL = re.compile(r"\b(photo-?real\w*|realis(m|tic)|hyper-?real\w*|ultra-?real\w*|lifelike|true[- ]to[- ]life|skin (texture|detail)|natural skin|pores|unretouched|candid photo|raw photo)\b", re.I)
PROMPT_RULES = {
    "realism": {"label": "Real skin and hair", "when": lambda t: bool(_REAL.search(t)),
                "text": "Skin should look photographed, not retouched: visible pores, fine lines, small blemishes and natural colour variation (warmer nose and cheeks, "
                        "cooler under the eyes), a slight natural sheen on the forehead and nose, and normal facial asymmetry. Eyes are moist with a real catchlight "
                        "and individual lashes. Hair falls as separate strands with flyaways and baby hairs, some crossing the face and casting small shadows. "
                        "No airbrushing, plastic or waxy skin, or beauty filter."},
    "capture": {"label": "Looks like a real camera", "when": lambda t: bool(_REAL.search(t)),
                "text": "It should read as a photo a real camera took: fine grain, focus that falls off naturally away from the subject, highlights allowed to clip, "
                        "no digital over-sharpening, HDR look, glow around the subject or glossy CGI finish. Keep the framing, lens and lighting asked for above."},
    "ugc": {"label": "Natural UGC acting", "when": lambda t: bool(re.search(r"\b(ugc|user[- ]generated|talking head|selfie video|vlog|testimonial)\b", t, re.I)),
            "text": "Film it like a real person recording themselves on a phone: the camera is hand-held or propped, so the framing drifts a little. They blink "
                    "naturally and irregularly, glance away and back to the lens, start mid-thought, and include one small unplanned moment (touching their hair, "
                    "a breath, a tiny stumble). Casual, believable, not a polished presenter."},
}

# ---------- face masks: Seedance (and BytePlus) turn away photos with real faces, so faces are covered with a white cross ----------
FACE_STRICT = re.compile(r"seedance|byteplus", re.I)
FACE_RULE = ("Note: the white cross shapes covering faces in the reference images are privacy masks added by the editor. They are not in the scene "
             "and not worn by anyone. Never draw, keep or animate them: show every face as a normal, uncovered human face.")


def face_mask(path, boxes=None):
    """A copy of an image with each face covered by a white cross. boxes: [{x, y, w, h}] in pixels; found automatically when not given."""
    from PIL import Image, ImageDraw
    src = (DATA / str(path).lstrip("@")).resolve()
    if DATA.resolve() not in src.parents or not src.is_file():
        raise RuntimeError("Can only mask files in your studio folder")
    if boxes is None:  # Florence-2 finds the faces (fractions of a cent)
        r = fal("https://fal.run/fal-ai/florence-2-large/open-vocabulary-detection", {"image_url": fal_file(src), "text_input": "human face"})
        boxes = [b for b in (r.get("results") or {}).get("bboxes", []) if b.get("w", 0) > 8]
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    for b in boxes:
        x, y, w, h = (float(b[k]) for k in ("x", "y", "w", "h"))
        cx, cy = x + w / 2, y + h * 0.45  # a little above centre: eyes, nose and mouth
        d.rectangle([cx - w * 0.24, y - h * 0.05, cx + w * 0.24, y + h * 1.02], fill="white")
        d.rectangle([x - w * 0.06, cy - h * 0.2, x + w * 1.06, cy + h * 0.2], fill="white")
    name = f"{uuid.uuid4().hex[:8]}_{mention_name(src.name)}_facemask.png"
    im.save(UPLOADS / name)
    return {"value": f"@uploads/{name}", "boxes": boxes, "faces": len(boxes)}


LIBRARY_FILE = DATA / "library.json"


def library():
    """Saved elements: [{id, name, kind (character/product/location/style), files: [@paths], notes}]."""
    try:
        return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def tag(name):
    """How a library item is written after @: its name with spaces as dashes ("Red Sneaker" -> Red-Sneaker)."""
    return re.sub(r"[^\w-]+", "-", str(name)).strip("-")


def media_kind(path):
    ext = Path(str(path).split("?")[0]).suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), "image")


def mention_name(path):
    """What you type after @ for a file: its name without the upload's random prefix or extension."""
    return re.sub(r"^[0-9a-f]{8}_", "", Path(str(path)).stem)


def _strings(v):
    return [v] if isinstance(v, str) else [x for i in v for x in _strings(i)] if isinstance(v, list) else []


def is_file(v):
    return isinstance(v, str) and v.startswith("@") and bool(re.search(r"\.\w{2,5}$", v))


def mention_targets(body):
    """Files a mention can mean: ones already in this run's settings, then every upload, newest first."""
    inside = [v for v in _strings(list(body.values())) if is_file(v)]
    ups = sorted((p for p in UPLOADS.glob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    return list(dict.fromkeys(inside + ["@uploads/" + p.name for p in ups]))


def find_mention(name, targets):
    n = name.lower()
    return (next((t for t in targets if Path(t).stem.lower() == n), None)  # the full saved name
            or next((t for t in targets if mention_name(t).lower() == n), None))


def resolve_mentions(body, schema):
    """Mark each @name in the text settings with its file, and make sure the model receives that file."""
    files = compare._files(schema) if schema else {}
    targets, used = None, []

    items, described = None, set()

    def sub(m):
        nonlocal targets, items
        items = items if items is not None else {tag(i["name"]).lower(): i for i in library() if i.get("name")}
        item = items.get(m.group(1).lower())
        if item and item.get("files"):  # a library element: all its reference files, and its description the first time
            used.extend(item["files"])
            text = " and ".join(f"@[{f}]" for f in item["files"])
            if item.get("notes") and item["name"] not in described:
                described.add(item["name"])
                text += f" ({item['name']}: {item['notes']})"
            return text
        if item and item.get("notes"):  # a style or brand with no files: its description
            return item["notes"]
        targets = targets if targets is not None else mention_targets(body)
        t = find_mention(m.group(1), targets)
        if t:
            used.append(t)
        return f"@[{t}]" if t else m.group(0)  # not a file's name (an email, a handle): leave it as typed
    for k, v in list(body.items()):
        if isinstance(v, str) and k not in files and "@" in v:
            body[k] = MENTION.sub(sub, v)
    present = set(_strings([body.get(k) for k in files]))
    for t in dict.fromkeys(used):
        if t in present or not files:
            continue
        kind = media_kind(t)
        slots = sorted(((k, many, role, mx) for k, (kd, many, role, mx) in files.items() if kd == kind and role != "last"),
                       key=lambda s: not s[1])  # lists first
        for k, many, role, mx in slots:
            cur = body.get(k)
            if many and len(cur or []) < (mx or 99):
                body[k] = list(cur or []) + [t]
                break
            if not many and not cur:
                body[k] = t
                break
        else:
            raise RuntimeError(f"Your prompt mentions @{mention_name(t)}, but this model has no free {kind} input for it. "
                               f"Remove one of its other {kind}s, or the mention.")
    return body


def mention_style(schema):
    """How the receiving model wants media referred to, read from its prompt's help text."""
    text = " ".join(str(p.get("description") or "") for k, p in (schema.get("properties") or {}).items() if "prompt" in k.lower())
    if re.search(r"@(Image|Video|Audio)\d", text):
        return lambda kind, n: f"@{kind.title()}{n}"
    m = re.search(r"\[(@?)reference_(image|video|audio)_\d\]", text)
    if m:
        return lambda kind, n: f"[{m.group(1) if kind != 'audio' else ''}reference_{kind}_{n}]"
    return lambda kind, n: f"{kind.title()} {n}"  # "Image 2": what models without a special syntax understand


def write_mentions(body, schema, job=None):
    """Turn @[file] marks into the model's own reference, numbered by where each file is in what's sent."""
    if not any(MARK.search(v) for v in body.values() if isinstance(v, str)):
        return body
    files = compare._files(schema) if schema else {}
    order = [k for k in (schema.get("x-fal-order-properties") or schema.get("properties") or {}) if k in files] if files else list(body)
    place, counts = {}, {}
    for k in order:
        for v in _strings(body.get(k)):
            if is_file(v) or v.startswith("http"):
                kind = files[k][0] if k in files else media_kind(v)
                counts[kind] = counts.get(kind, 0) + 1
                place.setdefault(v, (kind, counts[kind]))
    style = mention_style(schema or {})

    def sub(m):
        if m.group(1) not in place:
            kind = media_kind(m.group(1))
            why = f"takes too few {kind}s to include it" if any(f[0] == kind for f in files.values()) else f"doesn't take {kind}s"
            raise RuntimeError(f"Your prompt mentions @{mention_name(m.group(1))}, but this model {why}. Pick a model that takes {kind}s, or remove the mention.")
        return style(*place[m.group(1)])
    for k, v in list(body.items()):
        if isinstance(v, str) and MARK.search(v):
            body[k] = MARK.sub(sub, v)
            if job is not None:
                job.setdefault("sent", {})[k] = body[k]  # shown on the result card: the prompt exactly as the model got it
    return body


# ---------- input nodes ----------
# The node editor's input nodes arrive as "values": [{id, type, value}]. Batch nodes turn into one run per prompt.

BATCH_TYPES = ("batch_prompt", "batch_negative", "batch_images", "batch_videos")
MEDIA_BATCHES = ("batch_images", "batch_videos")  # value: [[files for run 1], [files for run 2], ...]


def parse_batch(text):
    kept = "\n".join(l for l in str(text).splitlines() if not l.lstrip().startswith("#"))
    return [p.strip() for p in re.split(r"(?m)^\s*---\s*$", kept) if p.strip()]


def value_rows(values, steps):
    used = json.dumps(steps)
    values = [v for v in values or [] if "{{" + v["id"] + "}}" in used]  # only nodes that are wired up
    static = {v["id"]: v.get("value") for v in values if v.get("type") not in BATCH_TYPES}
    batches = [(v["id"], [g for g in v.get("value") or [] if g] if v["type"] in MEDIA_BATCHES else parse_batch(v.get("value", "")))
               for v in values if v.get("type") in BATCH_TYPES]
    for vid, items in batches:
        if not items:
            raise RuntimeError(f"Batch node {vid} is empty")
    n = max((len(items) for _, items in batches), default=1)
    # batch nodes pair up line by line; a shorter batch starts again from its first prompt
    return [static | {vid: items[r % len(items)] for vid, items in batches} for r in range(n)]


# ---------- job runner ----------

def gate_enter():
    global running
    with cond:
        cond.wait_for(lambda: running < settings["concurrency"])
        running += 1


def gate_exit():
    global running
    with cond:
        running -= 1
        cond.notify_all()


def download(url, job, step, n):
    """Save one output (a link, or a data URI from providers that answer with the file itself) under outputs/<day>/."""
    base = OUT / time.strftime("%Y-%m-%d") / f"{time.strftime('%H%M%S')}_{job['id'][:6]}_s{step}_{n}"
    base.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("data:"):
        head, _, b64 = url.partition(",")
        dest = base.with_suffix(mimetypes.guess_extension(head[5:].split(";")[0]) or ".bin")
        dest.write_bytes(base64.b64decode(b64))
        return dest.relative_to(DATA).as_posix()
    req = urllib.request.Request(url, headers={"User-Agent": providers.core.UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        ext = Path(urllib.parse.urlparse(url).path).suffix or mimetypes.guess_extension(r.headers.get_content_type() or "") or ".bin"
        dest = base.with_suffix(ext if len(ext) <= 6 else ".bin")
        with open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    return dest.relative_to(DATA).as_posix()


def run_job(job):
    gate_enter()
    try:
        if job["status"] == "cancelled":
            return
        vars = dict(job["vars"])
        for i, step in enumerate(job["steps"]):
            if job["status"] == "cancelled":
                return
            job.update(status="running", step=i, started=job.get("started") or time.time())
            body = clean(fill(step["inputs"], vars))
            brief = settings.get("brief", "").strip() if settings.get("brief_on") else ""
            pk = "prompt" if isinstance(body.get("prompt"), str) else next((k for k, v in body.items() if isinstance(v, str) and "prompt" in k.lower()
                                                                             and not re.search("negative|system", k.lower())), None)
            if brief and pk:
                body[pk] = f"{body[pk].rstrip().rstrip('.')}. {brief}"
                job.setdefault("sent", {})[pk] = body[pk]  # the card shows the prompt with the brief added
            if pk and isinstance(body.get(pk), str):
                extra = [r["text"] for rid, r in PROMPT_RULES.items() if (settings.get("rules") or {}).get(rid) and r["when"](body[pk])]
                if extra:
                    body[pk] = body[pk].rstrip() + "\n\n" + "\n\n".join(extra)
                    job.setdefault("sent", {})[pk] = body[pk]
            if pk and "_facemask" in json.dumps(body) and FACE_STRICT.search(step["model"]):
                body[pk] = body[pk].rstrip() + "\n\n" + FACE_RULE
                job.setdefault("sent", {})[pk] = body[pk]
            if "@" in json.dumps(body):
                try:
                    schema = get_schema(step["model"])
                except Exception:
                    schema = {}
                body = resolve_mentions(body, schema)
            model, note, asked_body = step["model"], None, body
            try:
                model, body, note = route(model, body)
            except Exception as e:
                print("price comparison skipped:", e)
            if note and note.get("est") is not None:
                job["est"] = round((job.get("est") or 0) + note["est"], 6)
            if note and (note["used"] != note["asked"] or note["cheaper"]):
                job.setdefault("routes", []).append({"step": i, **note})
            try:
                got = run_step(model, body, job)
            except Exception as e:
                if model == step["model"] or not providers.has_key(providers.split(step["model"])[0]):
                    raise  # nowhere else to run it: show the real error, not "isn't connected"
                # the cheaper provider failed: run where it was asked instead
                job["routes"][-1]["fallback"] = str(e)[:200]
                model, body = step["model"], asked_body
                got = run_step(model, body, job)
            if got is None:
                return  # cancelled
            result, urls = got
            charge(job, model, body, result)
            files = [download(u, job, i, n) for n, u in enumerate(urls)]
            urls = [u if u.startswith("http") else "@" + f for u, f in zip(urls, files)]  # files sent inline are passed on as the saved copy
            job["results"].append({"step": i, "model": model, "result": result, "urls": urls, "files": files})
            vars.update(prev=urls[0] if urls else "", prev_all=urls)
            if step.get("id"):  # node editor: later nodes reference this one as {{id}} / {{id_all}}
                vars.update({step["id"]: urls[0] if urls else "", step["id"] + "_all": urls})
        job["status"] = "done"
    except Exception as e:
        job.update(status="error", error=str(e))
    finally:
        gate_exit()
        job["finished"] = time.time()
        if job.get("results"):
            log_spend(job)
        with history_lock, open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(job) + "\n")


def run_step(model, body, job):
    if not providers.has_key(providers.split(model)[0]):
        if credits_mode():
            if not providers.MODULES["muselight"].url():
                raise RuntimeError("Muselight Credits isn't open yet. To run models now, turn on “Use my own provider accounts” in Connections.")
            raise RuntimeError("Sign in to Muselight Credits to run this (Credits, at the top)." if not providers.core.key("MUSELIGHT_TOKEN") else
                               "This model isn't available on Muselight Credits. To use it, turn on your own provider accounts in Connections.")
        raise RuntimeError(f"{providers.label(providers.split(model)[0])} isn't connected. Add its key in Connections, "
                           "or pick this model on a provider you're connected to.")
    try:
        schema = get_schema(model)
        body = fit_to_schema(body, schema)
    except Exception:
        schema = {}  # no schema: send as is
    body = write_mentions(body, schema, job)
    prov = providers.split(model)[0]
    body = local_files(body, prov)
    got = fal_step(model, body, job) if prov == "fal" else providers.run(model, body, job)
    if got is not None and not got[1]:
        raise RuntimeError(f"{providers.label(prov)} finished but sent back no files")
    return got


def fal_step(model, body, job):
    """Run one step on fal's queue: (result, output urls), or None if cancelled."""
    sub = fal(f"https://queue.fal.run/{model}", body)
    job["request_id"] = sub.get("request_id")
    misses = 0  # status checks in a row that failed to reach fal
    while True:
        if job["status"] == "cancelled":
            if sub.get("cancel_url"):
                try:
                    fal(sub["cancel_url"], method="PUT")
                except RuntimeError:
                    pass  # already finished on fal's side
            return None
        try:
            status = fal(sub["status_url"])
            misses = 0
        except (urllib.error.URLError, TimeoutError, OSError, providers.core.Busy) as e:
            misses += 1
            if misses > 10:
                raise RuntimeError(f"Lost connection to fal while waiting for the result ({str(e)[:120]})")
            time.sleep(3)
            continue
        job["queue_position"] = status.get("queue_position")
        if status["status"] == "COMPLETED":
            break
        time.sleep(2)
    result = fal(sub["response_url"])
    urls = list(output_urls(result))
    return result, urls


def rewrite_history():
    """Keep the history file in step with what the app shows (last 300 finished runs)."""
    done = sorted((j for j in list(jobs.values()) if j["status"] not in ("queued", "running")), key=lambda j: j["created"])[-300:]
    with history_lock:
        HISTORY_FILE.write_text("".join(json.dumps(j) + "\n" for j in done), encoding="utf-8")


def failed_job(name, steps, error):
    """Show a problem in Results (e.g. from an automation) instead of hiding it in a log."""
    job = {"id": uuid.uuid4().hex, "name": name, "steps": steps or [{"model": "", "inputs": {}}], "vars": {}, "status": "error",
           "created": time.time(), "finished": time.time(), "results": [], "error": str(error)}
    jobs[job["id"]] = job
    with history_lock, open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(job) + "\n")


def submit(name, steps, rows, repeat, values=None, over_budget_ok=False, origin=""):
    if not over_budget_ok and over_budget():
        raise RuntimeError(over_budget() + " Raise the budget (click Spend at the top), or confirm to go over it.")
    rows = [v | r for v in value_rows(values, steps) for r in (rows or [{}])]
    created = []
    for _ in range(max(1, int(repeat))):
        for row in rows:
            job = {"id": uuid.uuid4().hex, "name": name or steps[0]["model"], "steps": steps, "vars": row,
                   "status": "queued", "created": time.time(), "results": [], "error": None, "origin": str(origin or "")[:20]}
            jobs[job["id"]] = job
            pool.submit(run_job, job)
            created.append(job["id"])
    return created


# ---------- workflows and automations ----------

def safe_name(name):
    return re.sub(r"[^\w\- ]", "", name).strip() or "untitled"


def load_workflow(name):
    return json.loads((WORKFLOWS / f"{safe_name(name)}.json").read_text(encoding="utf-8"))


def automation_loop():
    while True:
        for a in list(settings["automations"]):
            if not a.get("enabled"):
                continue
            try:
                watch(a)
            except Exception as e:
                print(f"automation {a.get('name')} skipped:", e)
        time.sleep(5)


def watch(a):
    folder = Path(a["folder"])
    if not folder.is_dir():
        return
    done = folder / "processed"
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in MEDIA and time.time() - f.stat().st_mtime > 3:  # still copying otherwise
            done.mkdir(exist_ok=True)
            target = done / f.name
            if target.exists():
                target = done / f"{f.stem}_{uuid.uuid4().hex[:6]}{f.suffix}"
            shutil.move(str(f), target)
            try:
                wf = load_workflow(a["workflow"])
                submit(f"{a['name']}: {f.name}", wf["steps"], [{"input": f"@{target}", "filename": f.stem}], 1, wf.get("values"), origin="auto")
            except Exception as e:
                failed_job(f"{a['name']}: {f.name}", None, f"Automation couldn't start: {e}")


def save_settings():
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# ---------- HTTP ----------

def job_summary(job):
    return {k: v for k, v in job.items() if k != "results"} | {
        "files": [f for r in job["results"] for f in r["files"]],
        "urls": [u for r in job["results"] for u in r["urls"]],
        "step_files": [r["files"] for r in job["results"]],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200, ctype="application/json", cache=False, etag=None):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "max-age=31536000, immutable" if cache else "no-cache")
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def trusted(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost"):
            return False
        if origin and urllib.parse.urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return self.send({"error": "forbidden"}, 403)
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                return self.send((ASSETS / "studio_ui.html").read_text(encoding="utf-8").replace("?v=ICONV", f"?v={ICON_VERSION}").encode(), ctype="text/html; charset=utf-8")
            if u.path == "/AGENT_GUIDE.md":
                return self.send((ASSETS / "AGENT_GUIDE.md").read_bytes(), ctype="text/markdown; charset=utf-8")
            if u.path in ("/favicon.ico", "/manifest.json") or re.fullmatch(r"/icons/icon_\d+\.png", u.path):  # app window + taskbar icon
                if u.path == "/manifest.json":
                    return self.send({"name": "Muselight", "short_name": "Muselight", "display": "standalone", "start_url": "/",
                                      "background_color": "#080c0a", "theme_color": "#080c0a",
                                      "icons": [{"src": f"/icons/icon_{n}.png?v={ICON_VERSION}", "sizes": f"{n}x{n}", "type": "image/png"} for n in (48, 96, 192, 256, 512)]},
                                     ctype="application/manifest+json")
                f = ASSETS / ("muselight.ico" if u.path == "/favicon.ico" else u.path[1:])
                return self.send(f.read_bytes(), ctype="image/x-icon" if f.suffix == ".ico" else "image/png", cache=True)
            if u.path == "/api/state":
                page["seen"] = time.time()
                state = json.dumps({
                    "key_set": bool(providers.connected()), "providers": [providers.label(p) for p in providers.connected()], "settings": settings, "running": running,
                    "credits_mode": credits_mode(), "credits_live": bool(providers.MODULES["muselight"].url()),
                    "spent_month": round(month_spend(), 4),
                    "jobs": sorted((job_summary(j) for j in list(jobs.values())), key=lambda j: -j["created"]),
                    "workflows": sorted(p.stem for p in WORKFLOWS.glob("*.json")),
                })
                tag = f'"{hash(state) & 0xFFFFFFFF:x}"'
                if self.headers.get("If-None-Match") == tag:  # nothing changed since the page last asked
                    self.send_response(304)
                    self.send_header("ETag", tag)
                    self.end_headers()
                    return
                return self.send(state.encode(), etag=tag)
            if u.path == "/api/schema":
                return self.send(get_schema(q["model"][0]))
            if u.path == "/api/connections":
                return self.send(connection_list())
            if u.path == "/api/credits":
                return self.send(credits_status())
            if u.path == "/api/agent/providers":
                return self.send(agent.provider_status())
            if u.path == "/api/agent/connector":
                command, args = (sys.executable, ["--mcp"]) if FROZEN else (sys.executable, [str(ROOT / "fal_mcp.py")])
                return self.send({"command": command, "args": args, "http_args": args + ["--http"], "guide": str(DATA / "AGENT_GUIDE.md"),
                                  "json": json.dumps({"mcpServers": {"muselight": {"command": command, "args": args}}}, indent=2)})
            if u.path == "/api/agent/models":
                return self.send(agent.list_models(q["provider"][0]))
            if u.path == "/api/agent/chat":
                return self.send(agent.chats[q["id"][0]].view())
            if u.path == "/api/params":
                return self.send(get_params())
            if u.path == "/api/models":
                return self.send(all_models(force="refresh" in q) if "all" in q else get_models(force="refresh" in q))
            if u.path == "/api/job":
                if q["id"][0] not in jobs:
                    raise RuntimeError("That run is no longer in the list")
                return self.send(jobs[q["id"][0]])
            if u.path == "/api/workflow":
                return self.send(load_workflow(q["name"][0]))
            if u.path == "/api/library":
                return self.send(library())
            if u.path == "/api/uploads":  # for the @ picker in prompts
                ups = sorted((p for p in UPLOADS.glob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)[:300]
                return self.send([{"path": "@uploads/" + p.name, "name": mention_name(p.name), "kind": media_kind(p.name)} for p in ups])
            if u.path == "/api/gpus":
                return self.send(gpu_overview())
            if u.path == "/api/runpod/gpus":
                return self.send(providers.runpod.gpus(q.get("product", ["SERVERLESS"])[0]))
            if u.path.startswith("/files/"):
                p = (DATA / urllib.parse.unquote(u.path[7:])).resolve()
                if DATA.resolve() not in p.parents or not p.is_file():
                    return self.send({"error": "not found"}, 404)
                import mimetypes
                return self.send(p.read_bytes(), ctype=mimetypes.guess_type(p)[0] or "application/octet-stream", cache=True)
            self.send({"error": "not found"}, 404)
        except Exception as e:
            self.send({"error": str(e)}, 400)

    def do_POST(self):
        if not self.trusted() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send({"error": "forbidden"}, 403)  # cross-site forms can't send JSON without asking first
        u = urllib.parse.urlparse(self.path)
        try:
            b = self.body()
            if u.path == "/api/run":
                if not b.get("steps"):
                    raise RuntimeError("Nothing to run")
                return self.send({"ids": submit(b.get("name"), b["steps"], b.get("rows"), b.get("repeat", 1), b.get("values"), bool(b.get("over_budget_ok")), b.get("origin"))})
            if u.path == "/api/connections":
                save_connection(b.get("name"), b.get("value"))
                return self.send({"ok": True})
            if u.path == "/api/connections/test":
                return self.send(test_connection(b.get("name")))
            if u.path.startswith("/api/credits/"):
                return self.send(credits_action(u.path.rsplit("/", 1)[1], b))
            if u.path == "/api/agent/tool":  # used by the MCP connector (fal_mcp.py)
                return self.send({"result": agent.connector_call(b["name"], b.get("args") or {})})
            if u.path == "/api/agent/new":
                return self.send(agent.new_chat(b["provider"], b.get("model"), b.get("auto")).view())
            if u.path.startswith("/api/agent/") and b.get("id") not in agent.chats:
                raise RuntimeError("That chat has ended. Start a new one.")
            if u.path == "/api/agent/send":
                c = agent.chats[b["id"]]
                if c.busy:
                    raise RuntimeError("The assistant is still working on your last message")
                if b.get("model"):
                    c.model = b["model"]
                c.send(b.get("text", ""), b.get("images") or [])
                return self.send(c.view())
            if u.path == "/api/agent/approve":
                agent.chats[b["id"]].answer(b["approval"], bool(b.get("ok")))
                return self.send({"ok": True})
            if u.path == "/api/agent/stop":
                agent.chats[b["id"]].stop = True
                return self.send({"ok": True})
            if u.path == "/api/agent/auto":
                agent.chats[b["id"]].auto = bool(b.get("auto"))
                return self.send({"ok": True})
            if u.path == "/api/cancel":
                for j in list(jobs.values()):
                    if (b.get("all") or j["id"] == b.get("id")) and j["status"] in ("queued", "running"):
                        j["status"] = "cancelled"
                return self.send({"ok": True})
            if u.path == "/api/clear":
                for k in [k for k, j in list(jobs.items()) if j["status"] not in ("queued", "running")]:
                    del jobs[k]
                rewrite_history()
                return self.send({"ok": True})
            if u.path == "/api/upload":
                name = f"{uuid.uuid4().hex[:8]}_{safe_name(Path(b['name']).stem)}{Path(b['name']).suffix.lower()}"
                (UPLOADS / name).write_bytes(base64.b64decode(b["data"].split(",")[-1]))
                return self.send({"value": f"@uploads/{name}"})
            if u.path == "/api/workflow":
                (WORKFLOWS / f"{safe_name(b['name'])}.json").write_text(json.dumps(b, indent=2), encoding="utf-8")
                return self.send({"ok": True})
            if u.path == "/api/workflow/delete":
                (WORKFLOWS / f"{safe_name(b['name'])}.json").unlink(missing_ok=True)
                return self.send({"ok": True})
            if u.path.startswith(("/api/comfy/", "/api/runpod/")):
                return self.send(gpu_action(u.path, b))
            if u.path == "/api/library":
                items = [dict(i, files=[f for f in i.get("files") or [] if isinstance(f, str)]) for i in b.get("items") or [] if str(i.get("name") or "").strip()]
                LIBRARY_FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")
                return self.send(items)
            if u.path == "/api/facemask":
                return self.send(face_mask(b["path"], b.get("boxes")))
            if u.path == "/api/producer":  # Marketing's ad producer chat
                return self.send({"text": producer(b.get("messages") or [], b.get("product") or {}, b.get("provider"), b.get("model"))})
            if u.path == "/api/product":  # Marketing: a shop link fills in the product
                return self.send(import_product(b["url"]))
            if u.path == "/api/score":  # hook / scroll-stop score for a result
                return self.send(score_media(b.get("images") or [], b.get("kind", "image"), b.get("context", ""), b.get("provider"), b.get("model")))
            if u.path == "/api/zip":  # a character's photos as one file, for identity training
                import zipfile
                name = f"{uuid.uuid4().hex[:8]}_{safe_name(b.get('name') or 'photos')}.zip"
                with zipfile.ZipFile(UPLOADS / name, "w") as z:
                    for i, f in enumerate(b.get("files") or []):
                        p = (DATA / str(f).lstrip("@")).resolve()
                        if DATA.resolve() in p.parents and p.is_file():
                            z.write(p, f"{i:02d}{p.suffix.lower()}")
                return self.send({"value": f"@uploads/{name}"})
            if u.path == "/api/write":  # Storyboard and Marketing: the assistant writes scenes or ad concepts
                return self.send({"text": agent.complete(b.get("provider"), b.get("model"), b.get("system") or "", b["prompt"])})
            if u.path == "/api/precheck":
                return self.send(precheck(b.get("steps") or [], b.get("rows"), b.get("values"), b.get("repeat", 1)))
            if u.path == "/api/prices":
                return self.send(price_view(b["model"], clean(b.get("inputs") or {}), bool(b.get("exact"))))
            if u.path == "/api/settings":
                with cond:
                    settings.update({k: v for k, v in b.items() if k in settings})
                    settings["concurrency"] = max(1, min(64, int(settings["concurrency"])))
                    cond.notify_all()
                save_settings()
                if "own_providers" in b:
                    apply_mode()
                return self.send(settings)
            if u.path == "/api/bye":  # the page is closing (or reloading: it checks in again straight away)
                page["bye"] = time.time()
                return self.send({"ok": True})
            if u.path == "/api/quit":
                self.send({"ok": True})
                threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
                return
            if u.path == "/api/open":
                target = (DATA / b.get("path", "outputs")).resolve()
                if target != DATA.resolve() and DATA.resolve() not in target.parents:
                    raise RuntimeError("Can only open folders inside studio_data")
                target = target if target.is_dir() else target.parent
                os.startfile(target) if os.name == "nt" else subprocess.Popen(["xdg-open", str(target)])
                return self.send({"ok": True})
            self.send({"error": "not found"}, 404)
        except Exception as e:
            self.send({"error": str(e)}, 400)


def gpu_overview():
    """What the GPUs panel shows: ComfyUI on this PC (or a server), your workflows, and your RunPod account."""
    cu = providers.comfyui
    out = {"comfy_url": cu.base(), "comfy_saved": bool(os.environ.get("COMFYUI_URL")), "comfy_ready": cu.ready(),
           "workflows": [{"name": n, "settings": list(cu.parse(w)[0]["properties"])} for n, w in cu.workflows().items()],
           "runpod": providers.has_key("runpod"), "variants": providers.runpod.COMFY_VARIANTS, "llm_models": list(providers.runpod.LLM_MODELS),
           "assistant_endpoint": os.environ.get("RUNPOD_LLM_ENDPOINT", "")}
    if out["runpod"]:
        for key, fn in (("balance", providers.runpod.balance), ("endpoints", providers.runpod.my_endpoints), ("pods", providers.runpod.pods)):
            try:
                out[key] = fn()
            except Exception as e:
                out[key + "_error"] = str(e)
    return out


def gpu_action(path, b):
    rp, cu = providers.runpod, providers.comfyui
    refresh = lambda: threading.Thread(target=provider_models, args=("runpod", True), daemon=True).start()
    if path == "/api/comfy/workflow":
        wf = cu.check_api_format(json.loads(b["workflow"]) if isinstance(b["workflow"], str) else b["workflow"])
        name = safe_name(b.get("name") or "workflow")
        (cu.folder() / f"{name}.json").write_text(json.dumps(wf, indent=1), encoding="utf-8")
        refresh()
        return {"ok": True, "name": name, "settings": list(cu.parse(wf)[0]["properties"])}
    if path == "/api/comfy/workflow/delete":
        (cu.folder() / f"{safe_name(b['name'])}.json").unlink(missing_ok=True)
        refresh()
        return {"ok": True}
    if path == "/api/runpod/deploy_comfy":
        r = rp.deploy_comfy(b["variant"], b["pool"], int(b.get("max_workers") or 2))
    elif path == "/api/runpod/inspect_llm":  # any chat model (Hugging Face, Hugging Bay, ModelScope, a mirror): its size, GPU and tool-call format
        return rp.inspect_llm(b.get("model", ""), b.get("hf_token", ""), b.get("source") or "huggingface")
    elif path == "/api/runpod/deploy_llm":
        r = rp.deploy_llm(b["model"], b["pool"], int(b.get("max_len") or 16384), b.get("parser"), b.get("reasoning"), b.get("hf_token"),
                          b.get("source") or "huggingface", b.get("base") or "", b.get("weights_gb") or 0)
        save_connection("RUNPOD_LLM_ENDPOINT", r["id"])  # the new model becomes the assistant's
    elif path == "/api/runpod/delete_endpoint":
        rp.delete_endpoint(b["id"])
        if os.environ.get("RUNPOD_LLM_ENDPOINT") == b["id"]:
            save_connection("RUNPOD_LLM_ENDPOINT", "")
        r = {"ok": True}
    elif path == "/api/runpod/use_assistant":
        save_connection("RUNPOD_LLM_ENDPOINT", b["id"])
        r = {"ok": True}
    elif path == "/api/runpod/pod":
        r = rp.pod_action(b["id"], b["action"])
    elif path == "/api/runpod/create_pod":
        r = rp.create_comfy_pod(b["gpu"])
    elif path == "/api/runpod/use_pod":
        save_connection("COMFYUI_URL", b["url"])
        r = {"ok": True}
    else:
        raise RuntimeError("Unknown action")
    refresh()
    return r


def load_state():
    for d in (OUT, UPLOADS, WORKFLOWS):
        d.mkdir(parents=True, exist_ok=True)
    guide = ASSETS / "AGENT_GUIDE.md"  # agents read it from disk, so keep a current copy beside the user's files
    if guide.exists() and guide != DATA / guide.name:
        shutil.copyfile(guide, DATA / guide.name)
    if SETTINGS_FILE.exists():
        settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    apply_mode()
    providers.MODULES["muselight"].prefer = lambda mid: (settings.get("credit_suppliers") or {}).get(mid) or None
    if HISTORY_FILE.exists():
        # ponytail: history loads the last 300 runs into memory; switch to paging if it gets slow
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-300:]:
            try:
                j = json.loads(line)
            except ValueError:
                continue  # a half-written line from a crash
            jobs[j["id"]] = j
        if len(lines) > 400:
            rewrite_history()


def should_quit(seen, bye, now, started):
    if bye and seen < bye and now - bye > 5:  # said goodbye and didn't come back (a reload checks in within a second)
        return True
    if not seen:
        return now - started > 120  # the window never showed up
    return now - seen > 300  # gone without a goodbye (e.g. crashed); generous because minimised pages check in slowly


def find_browser():
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
        if Path(exe).exists():
            return exe


ICON_VERSION = hashlib.sha256((ASSETS / "muselight.ico").read_bytes()).hexdigest()[:10]  # changes with the icon, so windows never show a cached old one


def fresh_icons():
    """The app window's browser keeps its own copy of the icon; after an icon change, drop that copy once so the taskbar and title bar update."""
    prof, mark = DATA / "window" / "Default", DATA / "window" / "icon_version.txt"
    if mark.exists() and mark.read_text().strip() == ICON_VERSION:
        return
    for name in ("Favicons", "Favicons-journal"):
        try:
            (prof / name).unlink(missing_ok=True)
        except OSError:
            return  # a window is still open; try again next start
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(ICON_VERSION)


def brand_windows():
    """Muselight's own taskbar button and sharp icon for the app window, instead of a resized browser favicon (Windows)."""
    try:
        import wintaskbar
        if FROZEN:
            wintaskbar.brand(ASSETS / "muselight.ico", f'"{sys.executable}"', sys.executable + ",0")
        else:
            pyw = Path(sys.executable).with_name("pythonw.exe")
            wintaskbar.brand(ROOT / "muselight.ico", f'"{pyw if pyw.exists() else sys.executable}" "{ROOT / "studio.py"}"')
    except Exception as e:
        print("taskbar icon:", e)


def open_window(url):
    """Open the app in its own window. Returns the window's process when we can tell when it closes."""
    fresh_icons()
    exe = find_browser()
    if not exe:
        webbrowser.open(url)
        return None
    # its own browser profile: a separate process we can wait on, and the page's saved preferences stay with the app
    return subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={DATA / 'window'}", "--window-size=1500,950",
                             "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"])


def already_running():
    try:
        port = int(PORT_FILE.read_text())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/agent/providers", timeout=2) as r:
            r.read()
        return port
    except Exception:
        return None


def start_server():
    for port in (PORT, 0):  # 0 = any free port, if ours is taken by something else
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if "PORT" not in os.environ:  # test copies on another port mustn't redirect the connector
        PORT_FILE.write_text(str(server.server_address[1]))
    return server


def attach_stdio():
    """The windowed .exe starts without stdin/stdout; pick up the pipes an agent app hands us so the connector can talk."""
    if sys.stdin is not None and sys.stdout is not None:
        return
    import ctypes, io, msvcrt
    get = ctypes.windll.kernel32.GetStdHandle
    get.restype = ctypes.c_void_p
    for which, name, mode in ((-10, "stdin", "rb"), (-11, "stdout", "wb"), (-12, "stderr", "wb")):
        handle = get(which)
        if handle and handle != ctypes.c_void_p(-1).value:
            stream = open(msvcrt.open_osfhandle(handle, 0), mode)
            setattr(sys, name, io.TextIOWrapper(stream, encoding="utf-8", write_through=mode == "wb"))


def main():
    if "--mcp" in sys.argv:  # started by an agent app as the Muselight connector
        try:
            if FROZEN:
                attach_stdio()
            import fal_mcp
            return fal_mcp.main(http="--http" in sys.argv)
        except BaseException:
            import traceback  # no console here, so leave the reason where the user can find it
            DATA.mkdir(exist_ok=True)
            (DATA / "connector_error.log").write_text(traceback.format_exc(), encoding="utf-8")
            raise
    agent.init(sys.modules[__name__])
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        agent.selftest()
        providers.selftest()
        return
    load_state()
    port = already_running()
    if port and "--no-window" not in sys.argv:
        open_window(f"http://127.0.0.1:{port}/")  # second launch: show the running app
        return
    load_connections()
    threading.Thread(target=automation_loop, daemon=True).start()
    server = start_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Muselight running at {url}  (keys: {', '.join(providers.label(p) for p in providers.connected()) or 'none yet'})", flush=True)
    if "--no-window" in sys.argv:
        return server.serve_forever()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    open_window(url)
    # Quit when the page is gone. Browsers often hand the window to another process, so watching the
    # process we started isn't reliable; the page checks in every couple of seconds instead.
    started = time.time()
    while True:
        time.sleep(1)
        if should_quit(page["seen"], page["bye"], time.time(), started):
            os._exit(0)
        if time.time() - started < 60 or int(time.time()) % 5 == 0:  # new windows (a second launch opens one) get it too
            brand_windows()


def selftest():
    import py_compile  # every file that ships in the .exe must at least compile
    compare.selftest()
    for f in ["agent.py", "fal_mcp.py", "fal_run.py", "wintaskbar.py"] + [f"providers/{x.name}" for x in (ROOT / "providers").glob("*.py")]:
        py_compile.compile(str(ROOT / f), doraise=True)
    v = {"line": "a cat", "prev": "https://x/1.png", "prev_all": ["https://x/1.png", "https://x/2.png"]}
    assert fill("photo of {{line}}", v) == "photo of a cat"
    assert fill(["{{n1}}", "{{n2_all}}"], {"n1": "u1", "n2_all": ["u2", "u3"]}) == ["u1", "u2", "u3"]
    assert fill({"image_urls": ["{{prev_all}}", "@hero.png"]}, v) == {"image_urls": ["https://x/1.png", "https://x/2.png", "@hero.png"]}
    assert fill({"image_url": "{{prev}}", "seed": 5, "x": "{{missing}}"}, v) == {"image_url": "https://x/1.png", "seed": 5, "x": "{{missing}}"}
    assert clean({"a": "", "b": None, "c": 0, "d": False, "e": []}) == {"c": 0, "d": False}
    comps = {"Size": {"type": "object", "properties": {"w": {"type": "integer"}}}}
    assert providers.core.resolve({"anyOf": [{"$ref": "#/components/schemas/Size"}]}, comps)["anyOf"][0]["properties"]["w"]["type"] == "integer"
    assert providers.core.fal_price({"unit": "minutes", "unit_price": 0.6}) == {"usd": 0.01, "per": "second"} and providers.core.fal_price({"unit": "token"}) is None
    assert safe_name("../evil name!") == "evil name"
    assert fal_error(422, '{"detail":[{"loc":["body","prompt"],"msg":"Field required"}]}') == "fal didn't accept these settings: prompt: Field required"
    assert fal_error(401, '{"detail":"nope"}').startswith("fal didn't accept your key")
    assert parse_batch("# help\nfirst prompt\n---\n# note\nsecond\nline two\n---\n\n") == ["first prompt", "second\nline two"]
    steps = [{"model": "m", "inputs": {"prompt": "{{v1}}", "negative_prompt": "{{v2}}", "seed": "{{v3}}"}}]
    rows = value_rows([{"id": "v1", "type": "batch_prompt", "value": "a\n---\nb\n---\nc"},
                       {"id": "v2", "type": "batch_negative", "value": "x\n---\ny"},
                       {"id": "v3", "type": "param", "value": 7}, {"id": "v9", "type": "batch_prompt", "value": ""}], steps)
    assert rows == [{"v3": 7, "v1": "a", "v2": "x"}, {"v3": 7, "v1": "b", "v2": "y"}, {"v3": 7, "v1": "c", "v2": "x"}], rows
    # image groups pair with prompts run by run; each run gets its whole group
    rows = value_rows([{"id": "v1", "type": "batch_prompt", "value": "a\n---\nb"},
                       {"id": "v5", "type": "batch_images", "value": [["@x.png", "@y.png"], [], ["@z.png"]]}],
                      [{"model": "m", "inputs": {"prompt": "{{v1}}", "image_urls": ["{{v5}}"]}}])
    assert rows == [{"v1": "a", "v5": ["@x.png", "@y.png"]}, {"v1": "b", "v5": ["@z.png"]}], rows
    assert fill({"image_urls": ["{{v5}}"]}, rows[0]) == {"image_urls": ["@x.png", "@y.png"]}
    sch = {"properties": {"image_url": {"type": "string"}, "image_urls": {"type": "array", "maxItems": 2},
                          "video_url": {"anyOf": [{"type": "string"}, {"type": "null"}]}, "tags": {"type": "array"}}}
    assert fit_to_schema({"image_url": ["a", "b"], "image_urls": ["a", "b", "c"], "video_url": ["v"], "tags": [1, 2, 3]}, sch) ==         {"image_url": "a", "image_urls": ["a", "b"], "video_url": "v", "tags": [1, 2, 3]}
    # @mentions: matched to files, added to the model's images, written the way each model wants
    sch = {"properties": {"prompt": {"type": "string", "description": "Reference images using @Image1, @Image2"},
                          "image_urls": {"type": "array", "items": {"type": "string", "_fal_ui_field": "image"}}}}
    r = resolve_mentions({"prompt": "@dog sits, mail me@x.com, @nobody", "style": "@uploads/1234abcd_dog.png"}, sch)
    assert r["prompt"] == "@[@uploads/1234abcd_dog.png] sits, mail me@x.com, @nobody" and r["image_urls"] == ["@uploads/1234abcd_dog.png"], r
    b = {"prompt": "@[@uploads/a_cat.png] sits by @[@uploads/1234abcd_dog.png]", "image_urls": ["@uploads/1234abcd_dog.png", "@uploads/a_cat.png"]}
    assert write_mentions(dict(b), sch)["prompt"] == "@Image2 sits by @Image1"
    plain = {"properties": {"prompt": {"type": "string"}, "image_urls": sch["properties"]["image_urls"]}}
    assert write_mentions(dict(b), plain)["prompt"] == "Image 2 sits by Image 1"
    vidu = {"properties": {"prompt": {"description": "[@reference_image_1], [reference_audio_1]"}, "image_urls": sch["properties"]["image_urls"]}}
    assert write_mentions(dict(b), vidu)["prompt"] == "[@reference_image_2] sits by [@reference_image_1]"
    tgt = ["@uploads/1234abcd_dog.png", "@uploads/a_cat.png"]
    assert find_mention("dog", tgt) == tgt[0] and find_mention("1234abcd_dog", tgt) == tgt[0] and find_mention("cow", tgt) is None
    assert MENTION.findall("@hero, and @the-dog. mail a@b.com @[x]") == ["hero", "the-dog"]
    assert local_files("@hero walks in") == "@hero walks in"  # a prompt starting with @ isn't a file
    assert PROMPT_RULES["realism"]["when"]("a photorealistic portrait") and not PROMPT_RULES["realism"]["when"]("an anime girl")
    assert PROMPT_RULES["ugc"]["when"]("UGC video of her holding the bottle") and not PROMPT_RULES["ugc"]["when"]("a cinematic ad")
    saved_budget = settings.get("budget")
    try:
        settings["budget"] = 0.0
        assert over_budget(5) is None
        settings["budget"] = 0.000001
        assert "over your monthly budget" in over_budget(5)
    finally:
        settings["budget"] = saved_budget
    from PIL import Image
    probe = UPLOADS / "selftest_face.png"
    UPLOADS.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100), "black").save(probe)
    try:
        r = face_mask("@uploads/selftest_face.png", [{"x": 30, "y": 20, "w": 40, "h": 50}])
        m = Image.open(DATA / r["value"][1:])
        assert r["faces"] == 1 and m.getpixel((50, 40)) == (255, 255, 255) and m.getpixel((5, 95)) == (0, 0, 0)
        assert Image.open(probe).getpixel((50, 40)) == (0, 0, 0) and FACE_STRICT.search("bytedance/seedance-2.5/us/image-to-video")
        (DATA / r["value"][1:]).unlink()
    finally:
        probe.unlink(missing_ok=True)
    global library
    real_library, library = library, lambda: [{"name": "Red Sneaker", "files": ["@uploads/s1.png", "@uploads/s2.png"], "notes": "white sole"},
                                             {"name": "Noir", "files": [], "notes": "black and white, hard shadows"}]
    try:
        r = resolve_mentions({"prompt": "@Red-Sneaker on a rock, @red-sneaker again, @Noir"}, sch)
        assert r["prompt"] == "@[@uploads/s1.png] and @[@uploads/s2.png] (Red Sneaker: white sole) on a rock, @[@uploads/s1.png] and @[@uploads/s2.png] again, black and white, hard shadows", r
        assert r["image_urls"] == ["@uploads/s1.png", "@uploads/s2.png"]
        assert write_mentions(r, sch)["prompt"].startswith("@Image1 and @Image2 (Red Sneaker")
    finally:
        library = real_library
    global SETTINGS_FILE
    import tempfile
    real_settings, SETTINGS_FILE = SETTINGS_FILE, Path(tempfile.mkdtemp()) / "settings.json"  # never touch the user's real settings
    saved = {k: os.environ.get(k) for k in ("OLLAMA_URL",)}
    try:
        save_connection("OLLAMA_URL", "http://127.0.0.1:9/")
        assert os.environ["OLLAMA_URL"] == "http://127.0.0.1:9" and settings["urls"]["OLLAMA_URL"] == "http://127.0.0.1:9"
        assert next(c for c in connection_list() if c["name"] == "OLLAMA_URL")["source"] == "app"
        assert test_connection("OLLAMA_URL")["ok"] is False
        try:
            save_connection("OLLAMA_URL", "javascript:alert(1)")
            raise AssertionError("bad address accepted")
        except RuntimeError:
            pass
        save_connection("OLLAMA_URL", "")
        assert "OLLAMA_URL" not in settings["urls"] and "OLLAMA_URL" not in saved_in_app
        assert all("value" not in c for c in connection_list() if c["kind"] == "key")  # keys never go back to the page
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        SETTINGS_FILE = real_settings
    assert not should_quit(0, 0, 100, 0) and should_quit(0, 0, 200, 0)  # waits for the window, but not forever
    assert not should_quit(seen=50, bye=49, now=60, started=0)        # reloaded: checked in after the goodbye
    assert should_quit(seen=50, bye=51, now=57, started=0)            # closed: goodbye, then silence
    assert not should_quit(seen=50, bye=51, now=54, started=0)        # short grace period first
    assert not should_quit(seen=50, bye=0, now=200, started=0) and should_quit(seen=50, bye=0, now=400, started=0)
    print("selftest ok")


if __name__ == "__main__":
    main()
