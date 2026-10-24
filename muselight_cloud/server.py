"""Muselight Credits: the server that lets people pay you instead of connecting their own provider accounts.

Users top up a prepaid balance through Paddle (the merchant of record: it takes the card, handles sales tax/VAT, refunds and
chargebacks). The models on sale are fal's catalogue, but each run is bought from the cheapest source this server has a key for
(fal, Atlas Cloud, WaveSpeed, Runware, or the model maker's own API), with its settings translated by the app's price comparison.
The price is the market price (the middle of what the big suppliers list it at, + MARKUP) or your cost + MIN_MARGIN, whichever
is higher, quoted before the run and taken from the balance; a failed or cancelled run is refunded. Your provider keys never leave this server.
Afterwards each run's real bill is read where the source reports it (fal with an admin key, most others in their reply), and a
source model whose real cost beat its estimate gets its future costs raised to match, so a mispriced model can't keep losing money.

Standard library only; one SQLite file. Run: python server.py  (settings: see DEPLOY.md). Commands: prices | report | token <account
or email> | credit <account> <usd> <note> | selftest
"""
import hashlib, hmac, json, math, os, re, secrets, sqlite3, statistics, sys, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the app's providers package: every source, the price estimator, translation
import providers  # noqa: E402
from providers import _core as core, compare  # noqa: E402

env = os.environ.get
FAL_KEY, FAL_ADMIN_KEY = env("FAL_KEY", ""), env("FAL_ADMIN_KEY", "")
PADDLE_API_KEY, PADDLE_CLIENT_TOKEN, PADDLE_SECRET = env("PADDLE_API_KEY", ""), env("PADDLE_CLIENT_TOKEN", ""), env("PADDLE_WEBHOOK_SECRET", "")
PADDLE_PRODUCT = env("PADDLE_PRODUCT_ID", "")
PADDLE_LIVE = env("PADDLE_ENV", "sandbox") == "live"
PADDLE_API = "https://api.paddle.com" if PADDLE_LIVE else "https://sandbox-api.paddle.com"
PUBLIC_URL = env("PUBLIC_URL", "http://127.0.0.1:8080").rstrip("/")
ADMIN_TOKEN = env("ADMIN_TOKEN", "")
# the web app (muselight.studio/app): which sites may call this server, and how people sign in there
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in env("ALLOWED_ORIGINS", "https://muselight.studio,https://www.muselight.studio").split(",") if o.strip()}
SUPABASE_URL, SUPABASE_ANON_KEY = env("SUPABASE_URL", "").rstrip("/"), env("SUPABASE_ANON_KEY", "")  # email/password, Google and X sign-in
TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_NAME = env("TELEGRAM_BOT_TOKEN", ""), env("TELEGRAM_BOT_NAME", "")  # the Telegram login widget
TERMS_URL = env("TERMS_URL", "")
MARKUP = float(env("MARKUP", "0.05"))  # over the market's middle price: keeps you near what people would pay elsewhere
MIN_MARGIN = float(env("MIN_MARGIN", "0.30"))  # over your cost, at least: Paddle keeps about 5% + $0.50 of each top-up
MARKET = ("fal", "wavespeed", "atlas", "runware", "segmind", "deepinfra")  # big suppliers whose public price lists set "the market"
TIGHT_MARGIN = float(env("TIGHT_MARGIN", "0.15"))  # the floor instead for closed models: every supplier resells the maker's API near list price
# Closed models: only their maker runs them, so every supplier resells the same thing. Everything else has open weights that each
# supplier hosts on its own hardware, so results can differ and the user may pick one.
# ponytail: a hand-kept list of model families; a new closed family missing here just gets the 30% floor and a supplier choice.
CLOSED = re.compile(r"kling|minimax|hailuo|ideogram|recraft|blackforestlabs|flux-pro|flux-1\.1|flux-2-(pro|max|flex)|kontext[/-](pro|max)|"
                    r"pixverse|xai|grok|bytedance|seedance|seedream|google|veo|imagen|gemini|nano-banana|vidu|elevenlabs|pika|openai|"
                    r"gpt-image|sora|luma|photon|heygen|topaz|meshy|moonvalley|bria|tripo|hyper3d|rodin|mureka|decart|runway|midjourney|"
                    r"alibaba|wan-?2[.-]?[5-9]")
SUSPECT = 1 / 3  # a supplier price under a third of the market's middle is nearly always a price-list error (wrong units), not a bargain
SOURCES = [s.strip() for s in env("SOURCES", "").split(",") if s.strip()]  # limit which sources are used (default: every one with a key)
NOT_SOURCES = {"muselight", "comfyui"}  # Muselight itself, and ComfyUI (a GPU on someone's PC)
MIN_TOPUP, MAX_TOPUP = int(env("MIN_TOPUP", "10")), int(env("MAX_TOPUP", "500"))
NEW_DAYS, NEW_DAILY = int(env("NEW_ACCOUNT_DAYS", "7")), int(env("NEW_ACCOUNT_DAILY_TOPUP", "100"))  # card-fraud brake on young accounts
TRUST_PROXY = env("TRUST_PROXY", "1") == "1"  # behind the host's HTTPS proxy, the client's address is in X-Forwarded-For
DATA = Path(env("DATA_DIR", Path(__file__).parent / "data"))
DB_FILE, PRICES_FILE = DATA / "credits.db", DATA / "prices.json"
M = 1_000_000  # money is stored in millionths of a dollar

DATA.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(DB_FILE, check_same_thread=False, isolation_level=None)
db.row_factory = sqlite3.Row
lock = threading.RLock()  # one writer at a time: every balance change and its ledger line happen together
db.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE, email TEXT, created REAL, balance INTEGER DEFAULT 0,
                                     frozen INTEGER DEFAULT 0, terms TEXT);
CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY, account TEXT, kind TEXT, amount INTEGER, ref TEXT UNIQUE, meta TEXT, created REAL);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, account TEXT, model TEXT, base_est REAL, charged INTEGER, status TEXT, request_id TEXT,
                                 status_url TEXT, response_url TEXT, cancel_url TEXT, result TEXT, error TEXT, actual REAL, created REAL, finished REAL);
CREATE INDEX IF NOT EXISTS runs_open ON runs(status);
CREATE INDEX IF NOT EXISTS ledger_account ON ledger(account, created);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, account TEXT, created REAL);
""")
for table, col in (("accounts", "ext_id TEXT"), ("runs", "hidden INTEGER DEFAULT 0"), ("runs", "input TEXT")):
    try:  # ext_id: the sign-in it belongs to (sb:<Supabase user>, tg:<Telegram user>); hidden: removed from history; input: what was asked
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass
db.execute("CREATE UNIQUE INDEX IF NOT EXISTS accounts_ext ON accounts(ext_id) WHERE ext_id IS NOT NULL")
db.execute("CREATE INDEX IF NOT EXISTS runs_account ON runs(account, created)")
for col in ("source TEXT", "ref_est REAL"):  # added with cheapest-source buying: where each run was bought, and fal's price for it
    try:
        db.execute(f"ALTER TABLE runs ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass  # already there
db.execute("UPDATE runs SET source=model WHERE source IS NULL")
providers.init(DATA)  # sources cache their catalogues here


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def usd(micro):
    return round(micro / M, 6)


# ---------- money ----------

def move(account, kind, amount, ref, meta=None):
    """Change a balance and write the ledger line, together. A ref already used is a repeat (a webhook resent): nothing happens."""
    with lock:
        db.execute("BEGIN IMMEDIATE")
        try:
            if ref and db.execute("SELECT 1 FROM ledger WHERE ref=?", (ref,)).fetchone():
                db.execute("ROLLBACK")
                return False
            db.execute("INSERT INTO ledger (account, kind, amount, ref, meta, created) VALUES (?,?,?,?,?,?)",
                       (account, kind, amount, ref, json.dumps(meta or {}), time.time()))
            db.execute("UPDATE accounts SET balance = balance + ? WHERE id=?", (amount, account))
            db.execute("COMMIT")
            return True
        except Exception:
            db.execute("ROLLBACK")
            raise


verified = {}  # Supabase token hash -> (checked until, account id): a sign-in is confirmed with Supabase at most every few minutes


def account_by_token(token):
    """The account for a sign-in: a Muselight code or web session (kt_…), or a Supabase sign-in from the web app."""
    if not token:
        raise Refused(401, "Sign in to Muselight first.")
    h = hashlib.sha256(token.encode()).hexdigest()
    if token.startswith("kt_"):
        row = db.execute("SELECT * FROM accounts WHERE token_hash=? OR id=(SELECT account FROM sessions WHERE token_hash=?)", (h, h)).fetchone()
    else:
        until, aid = verified.get(h, (0, None))
        if until < time.time():
            aid = account_for(*supabase_user(token))
            verified[h] = (time.time() + 300, aid)
        row = db.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
    if not row:
        raise Refused(401, "Unknown Muselight account. Sign in again.")
    return row


def supabase_user(token):
    """(ext id, email) for a Supabase sign-in, asked of Supabase itself, so a forged token gets nowhere."""
    if not SUPABASE_URL:
        raise Refused(401, "Sign-in isn't set up on this server.")
    req = urllib.request.Request(SUPABASE_URL + "/auth/v1/user", headers={"apikey": SUPABASE_ANON_KEY, "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            u = json.load(r)
    except urllib.error.HTTPError:
        raise Refused(401, "Your sign-in has expired. Sign in again.")
    return "sb:" + u["id"], u.get("email")


def account_for(ext_id, email=None):
    """The account belonging to a sign-in, created on its first visit."""
    with lock:
        row = db.execute("SELECT id FROM accounts WHERE ext_id=?", (ext_id,)).fetchone()
        if row:
            if email:
                db.execute("UPDATE accounts SET email=COALESCE(email, ?) WHERE id=?", (email, row["id"]))
            return row["id"]
        aid = "acct_" + secrets.token_hex(8)
        db.execute("INSERT INTO accounts (id, created, terms, ext_id, email) VALUES (?,?,?,?,?)", (aid, time.time(), TERMS_URL, ext_id, email))
        return aid


def new_session(account):
    """A sign-in for one browser (Telegram); the desktop app's code keeps working alongside it."""
    token = "kt_" + secrets.token_urlsafe(32)
    with lock:
        db.execute("INSERT INTO sessions (token_hash, account, created) VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), account, time.time()))
    return token


def telegram_login(d):
    """Check the Telegram login widget's signature (HMAC with the bot token's hash) and sign that Telegram user in."""
    if not TELEGRAM_BOT_TOKEN:
        raise Refused(400, "Telegram sign-in isn't set up.")
    d = {k: str(v) for k, v in d.items() if v is not None}
    sig = d.pop("hash", "")
    check = "\n".join(f"{k}={d[k]}" for k in sorted(d))
    want = hmac.new(hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, sig) or time.time() - int(d.get("auth_date", 0)) > 86400:
        raise Refused(401, "That Telegram sign-in didn't check out. Try again.")
    return {"token": new_session(account_for("tg:" + d["id"]))}


def list_runs(acct, limit=60, before=None):
    """Your history, newest first."""
    rows = db.execute("SELECT * FROM runs WHERE account=? AND hidden=0 AND created < ? ORDER BY created DESC LIMIT ?",
                      (acct["id"], float(before or time.time() + 1), max(1, min(200, int(limit))))).fetchall()
    return [dict(run_view(r), model=r["model"], created=r["created"], input=json.loads(r["input"] or "{}")) for r in rows]


def hide_run(acct, rid):
    with lock:
        n = db.execute("UPDATE runs SET hidden=1 WHERE id=? AND account=? AND status IN ('done', 'failed', 'cancelled')", (rid, acct["id"])).rowcount
    if not n:
        raise Refused(404, "No finished run with that id.")
    return {"ok": True}


def brief(body):
    """What was asked, for the history (file contents and long values cut down)."""
    out = {}
    for k, v in body.items():
        if isinstance(v, str) and v.startswith("data:"):
            v = "[file]"
        out[k] = v if not isinstance(v, str) else v[:2000]
    return json.dumps(out)[:6000]


def new_token(account):
    token = "kt_" + secrets.token_urlsafe(32)
    with lock:
        db.execute("UPDATE accounts SET token_hash=? WHERE id=?", (hashlib.sha256(token.encode()).hexdigest(), account))
    return token


def create_account(accepted_terms):
    if TERMS_URL and not accepted_terms:
        raise Refused(400, "Accept the terms first.")
    aid = "acct_" + secrets.token_hex(8)
    with lock:
        db.execute("INSERT INTO accounts (id, created, terms) VALUES (?,?,?)", (aid, time.time(), TERMS_URL if accepted_terms else ""))
    return {"account_id": aid, "token": new_token(aid)}


def me(acct):
    return {"account_id": acct["id"], "balance": usd(acct["balance"]), "email": acct["email"], "frozen": bool(acct["frozen"]),
            "min_topup": MIN_TOPUP, "max_topup": topup_room(acct), "markup": MARKUP, "terms": TERMS_URL}


# ---------- prices ----------

prices = {}  # fal model id -> {name, cat, desc, thumb, cost: {usd, per}} (fal's list price)
schemas = {}


def fal(url, body=None, method=None, key=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method=method,
                                 headers={"Authorization": "Key " + (key or FAL_KEY), "Content-Type": "application/json", "User-Agent": core.UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
        return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        raise Refused(e.code if e.code in (400, 404, 422) else 502, core.api_error("fal", "your fal dashboard", e.code, text))


def refresh_prices():
    """Every fal model with a list price, saved to prices.json (run daily; takes a minute)."""
    models, cursor = [], None
    while True:
        d = fal("https://api.fal.ai/v1/models?limit=100" + (f"&cursor={cursor}" if cursor else ""))
        models += d.get("models", [])
        cursor = d.get("next_cursor")
        if not d.get("has_more"):
            break
    out = {}
    for i in range(0, len(models), 40):
        chunk = {m["endpoint_id"]: m for m in models[i:i + 40]}
        for attempt in range(5):
            try:
                rows = fal("https://api.fal.ai/v1/models/pricing?endpoint_id=" + ",".join(urllib.parse.quote(x, safe="/") for x in chunk)).get("prices", [])
                break
            except Refused:
                time.sleep(3 * (attempt + 1))  # fal limits how fast its pricing can be read
        else:
            continue
        for r in rows:
            cost, m = core.fal_price(r), chunk.get(r.get("endpoint_id"))
            if cost and m:
                md = m.get("metadata") or {}
                out[m["endpoint_id"]] = {"name": (md.get("display_name") or "").strip(), "cat": md.get("category", ""),
                                         "desc": (md.get("description") or "").strip()[:200], "thumb": md.get("thumbnail_url", ""), "cost": cost}
        time.sleep(1.5)
    if out:
        PRICES_FILE.write_text(json.dumps(out), encoding="utf-8")
        prices.clear(); prices.update(out)
        listing["t"] = 0
    return len(out)


def load_prices():
    if PRICES_FILE.exists():
        prices.update(json.loads(PRICES_FILE.read_text(encoding="utf-8")))


# ---------- sources: the same model at every provider this server has a key for ----------

catalog = {"t": 0, "items": {}, "index": {}}  # every source's models, matched to fal's by the app's comparison
listing = {"t": 0, "v": []}


def source_ids():
    """Where runs can be bought: fal, plus every provider whose key is set on this server (SOURCES narrows it)."""
    ids = (["fal"] if FAL_KEY else []) + [p for p in providers.MODULES if p not in NOT_SOURCES and providers.has_key(p)]
    return [p for p in ids if not SOURCES or p in SOURCES]


def build_catalog():
    """Every source's models and list prices, indexed by what model they are (refreshed daily)."""
    items = {mid: dict(item, prov="fal") for mid, item in prices.items()}
    for prov in sorted(set(source_ids()) | set(MARKET)):  # suppliers without a key here are listed for their prices only
        if prov != "fal" and prov in providers.MODULES:
            try:
                for m in providers.list_models(prov):  # the provider's label isn't part of what the model is
                    items[m["id"]] = dict(m, prov=prov, cat=m.get("cat", "").split("·")[-1].strip())
            except Exception as e:
                print(f"couldn't list {prov} models:", e, flush=True)
    index = {}
    for mid, m in items.items():
        key = compare.canon(providers.split(mid)[1], m.get("cat", ""))
        if key:
            index.setdefault(key, []).append(mid)
    catalog.update(t=time.time(), items=items, index=index)
    listing["t"] = 0


def cost_of(mid):
    item = catalog["items"].get(mid) or prices.get(mid) or {}
    if item.get("cost"):
        return item["cost"]
    prov, bare = providers.split(mid)
    m = providers.MODULES.get(prov)
    if m and hasattr(m, "cost") and "cost_lazy" not in item:
        try:
            item["cost_lazy"] = m.cost(bare)
        except Exception:
            item["cost_lazy"] = None
    return item.get("cost_lazy")


def schema_of(mid):
    if mid not in schemas:
        schemas[mid] = core.fal_schema(mid) if providers.split(mid)[0] == "fal" else providers.schema(mid)
    return schemas[mid]


factors = {"t": 0, "v": {}}


def correction(source):
    """How much more than its estimate this source model has really cost lately (never below 1): the worst of its last 20 runs."""
    if time.time() - factors["t"] > 60:  # one query for every source model, refreshed every minute
        rows = db.execute("SELECT source, MAX(actual / base_est) AS r FROM (SELECT source, actual, base_est, ROW_NUMBER() OVER "
                          "(PARTITION BY source ORDER BY created DESC) AS n FROM runs WHERE actual > 0 AND base_est > 0) WHERE n <= 20 GROUP BY source").fetchall()
        factors.update(t=time.time(), v={r["source"]: min(5.0, max(1.0, r["r"])) for r in rows})
    return factors["v"].get(source, 1.0)


def sell(cost, market, margin=None):
    """The price: the market's middle + MARKUP, unless your own cost + the minimum margin is higher."""
    return max(cost * (1 + (MIN_MARGIN if margin is None else margin)), market * (1 + MARKUP))


def listed(ests):
    """{supplier: its lowest listed price} for the big suppliers and this server's sources."""
    by = {}
    for prov, est in ests:
        if est and (prov in MARKET or prov in source_ids()):
            by[prov] = min(est, by.get(prov, est))
    return by


def middle(ests):
    """The market price of a run: the median of what each big supplier (or one of this server's sources) lists it at."""
    by = listed(ests)
    return statistics.median(by.values()) if by else None


def closed(model):
    """True for a model only its maker runs (every supplier resells the maker's API, so it's the same everywhere and margins are thin)."""
    return bool(CLOSED.search((model + " " + (prices.get(model) or {}).get("name", "")).lower()))


def trusted(est, market):
    """What to assume a source charges: its listed price, unless that's suspiciously far under the market. Then assume just enough
    that the run sells at the market price (real costs, read after each run, raise it if that was still too low)."""
    return market * (1 + MARKUP) / (1 + MIN_MARGIN) if market and est < market * SUSPECT else est


def plan(model, body, prefer=None):
    """What this run costs the user and where it's bought: {price (millionths), source, provider, body (in the source's names), base
    (its assumed cost), ref (fal's), market (the middle price), hosted (each supplier runs its own copy)}.
    Sources are tried cheapest first (after their learned correction); one that can't take these settings faithfully is skipped.
    prefer: a supplier the user chose (e.g. "runware"); only it is tried."""
    if model not in prices:
        raise Refused(404, f"{model} isn't available with Muselight Credits.")
    item_of = lambda mid: catalog["items"].get(mid) or (dict(prices[mid], prov="fal") if mid in prices else None)
    rows, src = compare.options(model, body, catalog["index"], item_of, schema_of, cost_of, lambda p: p in source_ids())
    market = middle((r["provider"], r["est"]) for r in rows)
    if market is None:
        raise Refused(404, f"No price is known for {model} yet.")
    hosted = not closed(model)
    margin = MIN_MARGIN if hosted else TIGHT_MARGIN
    fal_est = next((trusted(r["est"], market) for r in rows if r["model"] == model and r["est"]), market)
    picks = [(trusted(r["est"], market), r) for r in rows if r["connected"] and r["est"] and (not prefer or r["provider"] == prefer)]
    for base, r in sorted(picks, key=lambda c: c[0] * correction(c[1]["model"])):
        out = body
        if r["model"] != model:
            try:
                out, why = compare.translate(body, src, schema_of(r["model"]))
            except Exception:
                out = None
            if out is None:
                continue
        price = sell(base * correction(r["model"]), market, margin)
        cents10 = math.ceil(round(price * 1000, 6))  # rounded up to a tenth of a cent (round first: 0.05 * 1.1 is 0.05500000000000001)
        return {"price": max(1000, cents10 * 1000), "source": r["model"], "provider": r["provider"], "body": out, "base": base,
                "ref": fal_est, "market": market, "hosted": hosted}
    if prefer:
        name = providers.label(prefer) if prefer == "fal" or prefer in providers.MODULES else prefer
        raise Refused(409, f"{name} can't run this model with these settings. Choose another supplier, or Best price.")
    raise Refused(503, f"No source can run {model} right now.")


def quote(model, body, prefer=None):
    """(price in millionths, the source's estimated cost) for this run. The price is what the user pays, exactly."""
    p = plan(model, body, prefer)
    return p["price"], p["base"]


def quote_view(model, body, prefer=None):
    """What the apps show before a run: the price, who runs it, and, for models each supplier hosts itself, every supplier's price."""
    p = plan(model, body, prefer)
    out = {"price": usd(p["price"]), "provider": p["provider"], "provider_name": providers.label(p["provider"]), "hosted": p["hosted"]}
    if p["hosted"]:
        choices = []
        for prov in source_ids():
            try:
                c = plan(model, body, prov)
                choices.append({"id": prov, "name": providers.label(prov), "price": usd(c["price"])})
            except Refused:
                pass
        if len(choices) > 1:
            out["choices"] = sorted(choices, key=lambda c: c["price"])
    return out


def price_list():
    """Every model with its price per unit (for default settings; the quote for real settings is exact)."""
    if time.time() - listing["t"] < 600:
        return listing["v"]
    out, ok = [], set(source_ids())
    for mid, item in prices.items():
        ref = compare.estimate(item["cost"], {})
        members = set(catalog["index"].get(compare.canon(mid, item.get("cat", "")), [])) | {mid}
        ests = {s: compare.estimate(cost_of(s), {}) for s in members if cost_of(s)}
        market = middle((providers.split(s)[0], e) for s, e in ests.items()) or ref
        costs = [trusted(e, market) * correction(s) for s, e in ests.items() if e and providers.split(s)[0] in ok]
        ratio = sell(min(costs or [trusted(ref, market) * correction(mid)]), market, TIGHT_MARGIN if closed(mid) else None) / ref
        out.append({"id": mid, "name": item["name"], "cat": item["cat"], "desc": item["desc"], "thumb": item["thumb"],
                    "cost": {"usd": round(item["cost"]["usd"] * ratio, 6), "per": item["cost"]["per"]}})
    listing.update(t=time.time(), v=out)
    return out


# ---------- runs ----------

jobs = {}  # run id -> the job a non-fal source is working on (in this process)


def start_run(acct, model, body, prefer=None):
    if acct["frozen"]:
        raise Refused(403, "This account is on hold after a disputed payment. Contact support.")
    if not isinstance(body, dict):
        raise Refused(400, "Settings must be an object.")
    body = dict(body)
    if "enable_safety_checker" in (schema_of(model).get("properties") or {}):
        body["enable_safety_checker"] = True  # you're the provider now: the safety filter stays on (sources with the same setting get it too)
    p = plan(model, body, prefer)
    rid = "run_" + secrets.token_hex(10)
    with lock:
        bal = db.execute("SELECT balance FROM accounts WHERE id=?", (acct["id"],)).fetchone()["balance"]
        if bal < p["price"]:
            raise Refused(402, f"This run costs ${usd(p['price']):.3f} and your Muselight balance is ${usd(bal):.2f}. Top up under Credits.")
        db.execute("INSERT INTO runs (id, account, model, source, base_est, ref_est, charged, status, created, input) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (rid, acct["id"], model, p["source"], p["base"], p["ref"], p["price"], "submitting", time.time(), brief(body)))
        move(acct["id"], "run", -p["price"], "run:" + rid, {"model": model})
    if p["source"] == model:
        submit_fal(rid, model, p["body"])
    else:
        threading.Thread(target=run_elsewhere, args=(rid, p["source"], p["body"], model, body), daemon=True).start()
    return {"id": rid, "charged": usd(p["price"])}


def submit_fal(rid, model, body):
    try:
        sub = fal(f"https://queue.fal.run/{model}", body)
    except Exception as e:
        finish(rid, "failed", error=str(e))
        raise
    with lock:
        db.execute("UPDATE runs SET status='running', request_id=?, status_url=?, response_url=?, cancel_url=? WHERE id=?",
                   (sub.get("request_id"), sub.get("status_url"), sub.get("response_url"), sub.get("cancel_url"), rid))


def run_elsewhere(rid, source, body, model, fal_body):
    """Run on a cheaper source (in the background; the app keeps asking for the run's status). If it fails, fal does it instead."""
    job = jobs[rid] = {"status": "running"}
    with lock:
        db.execute("UPDATE runs SET status='running' WHERE id=?", (rid,))
    try:
        result, outs = providers.run(source, body, job)
        mod = providers.MODULES.get(providers.split(source)[0])
        try:
            actual = mod.charged(result) if hasattr(mod, "charged") else None
        except Exception:
            actual = None
        with lock:
            db.execute("UPDATE runs SET actual=? WHERE id=?", (actual, rid))
        finish(rid, "done", result={"result": result, "outputs": outs})
    except Exception as e:
        run = db.execute("SELECT charged, ref_est FROM runs WHERE id=?", (rid,)).fetchone()
        if not run["ref_est"] or run["ref_est"] * correction(model) * M > run["charged"]:  # fal would cost more than they paid: refund instead
            print(f"{source} failed ({str(e)[:200]}); fal costs more than this run's price, so it's refunded", flush=True)
            finish(rid, "failed", error="This model is busy right now. You weren't charged; try again in a minute.")
            return
        print(f"{source} failed ({str(e)[:200]}); running {model} on fal instead", flush=True)
        with lock:  # fal's own price is now the cost to compare against
            db.execute("UPDATE runs SET source=?, base_est=ref_est, error=? WHERE id=?", (model, f"{source}: {str(e)[:300]}", rid))
        try:
            submit_fal(rid, model, fal_body)
        except Exception:
            pass  # submit_fal has refunded it
    finally:
        jobs.pop(rid, None)


def finish(rid, status, result=None, error=None):
    """Close a run once. Failed and cancelled runs are refunded in full."""
    with lock:
        run = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if run["status"] in ("done", "failed", "cancelled"):
            return
        db.execute("UPDATE runs SET status=?, result=?, error=?, finished=? WHERE id=?",
                   (status, json.dumps(result) if result is not None else None, error if status != "done" else None, time.time(), rid))
        if status != "done":
            move(run["account"], "run_refund", run["charged"], "refund:" + rid, {"why": status})


def advance(run):
    """Check a run on fal's queue and close it when fal is done (runs elsewhere close themselves)."""
    if run["status"] != "running" or not run["status_url"]:
        return run
    try:
        st = fal(run["status_url"])
    except Refused as e:
        if e.code == 404:
            finish(run["id"], "failed", error="fal lost this request")
        return db.execute("SELECT * FROM runs WHERE id=?", (run["id"],)).fetchone()
    if st.get("status") == "COMPLETED":
        try:
            r = fal(run["response_url"])
            finish(run["id"], "done", result={"result": r, "outputs": core.media_urls(r)})
        except Refused as e:
            finish(run["id"], "failed", error=str(e))
    run = dict(db.execute("SELECT * FROM runs WHERE id=?", (run["id"],)).fetchone())
    run["queue_position"] = st.get("queue_position")
    return run


def run_view(run):
    out = {"id": run["id"], "status": run["status"], "charged": usd(run["charged"]), "queue_position": run.get("queue_position") if isinstance(run, dict) else None}
    if run["source"]:
        prov = providers.split(run["source"])[0]
        out["provider_name"] = providers.label(prov) if prov == "fal" or prov in providers.MODULES else prov
    if run["status"] == "done":
        out.update(json.loads(run["result"]))  # result, outputs
    elif run["error"]:
        out["error"] = run["error"]
    return out


def get_run(acct, rid):
    run = db.execute("SELECT * FROM runs WHERE id=? AND account=?", (rid, acct["id"])).fetchone()
    if not run:
        raise Refused(404, "No such run.")
    return run_view(advance(run))


def cancel_run(acct, rid):
    """Only a run still waiting in fal's queue can be cancelled (and refunded); one already working finishes and is delivered."""
    run = db.execute("SELECT * FROM runs WHERE id=? AND account=?", (rid, acct["id"])).fetchone()
    if not run:
        raise Refused(404, "No such run.")
    if run["status"] == "running" and run["cancel_url"]:
        try:
            fal(run["cancel_url"], method="PUT")
            finish(rid, "cancelled")  # nothing ran, so nothing is owed
        except Refused:
            pass
    return run_view(db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone())


def actual_cost(run):
    """What fal billed for one run (needs the fal admin key; the record appears a little after the run)."""
    d = fal("https://api.fal.ai/v1/models/billing-events?request_id=" + urllib.parse.quote(run["request_id"]), key=FAL_ADMIN_KEY)
    ev = d.get("billing_events") or []
    return sum(e.get("cost_total") or 0 for e in ev) if ev else None


def sweeper():
    """Every minute: close runs nobody is watching any more (so failures still get refunded), read fal's real costs,
    and refresh fal's prices and every source's catalogue once a day."""
    while True:
        time.sleep(60)
        try:
            for run in db.execute("SELECT * FROM runs WHERE status='running' AND status_url IS NOT NULL AND created < ?", (time.time() - 120,)).fetchall():
                advance(run)
            for run in db.execute("SELECT * FROM runs WHERE status IN ('submitting', 'running') AND status_url IS NULL AND created < ?",
                                  (time.time() - 1800,)).fetchall():
                if run["id"] not in jobs:  # lost in a restart
                    finish(run["id"], "failed", error="interrupted by a server restart")
            if FAL_ADMIN_KEY:
                for run in db.execute("SELECT * FROM runs WHERE actual IS NULL AND request_id IS NOT NULL AND finished BETWEEN ? AND ?",
                                      (time.time() - 86400, time.time() - 30)).fetchall():
                    cost = actual_cost(run)
                    if cost is not None:
                        with lock:
                            db.execute("UPDATE runs SET actual=? WHERE id=?", (cost, run["id"]))
            if time.time() - (PRICES_FILE.stat().st_mtime if PRICES_FILE.exists() else 0) > 86400:
                refresh_prices()
            if time.time() - catalog["t"] > 86400:
                build_catalog()
        except Exception as e:
            print("sweeper:", e, flush=True)


# ---------- top-ups (Paddle) ----------

def topup_room(acct):
    """The most this account may top up right now: young accounts get a daily cap, which limits what a stolen card can do."""
    if time.time() - acct["created"] > NEW_DAYS * 86400:
        return MAX_TOPUP
    day = db.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM ledger WHERE account=? AND kind='topup' AND created > ?",
                     (acct["id"], time.time() - 86400)).fetchone()["s"]
    return max(0, min(MAX_TOPUP, NEW_DAILY - int(day / M)))


def paddle(path, body=None):
    req = urllib.request.Request(PADDLE_API + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + PADDLE_API_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise Refused(502, "Paddle: " + core.api_error("Paddle", "your Paddle dashboard", e.code, e.read().decode(errors="replace")))


def start_topup(acct, amount):
    if acct["frozen"]:
        raise Refused(403, "This account is on hold after a disputed payment. Contact support.")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise Refused(400, "Pick an amount in whole dollars.")
    room = topup_room(acct)
    if amount < MIN_TOPUP or amount > room:
        raise Refused(400, f"Top up between ${MIN_TOPUP} and ${room} at a time." if room >= MIN_TOPUP else
                      "New accounts can top up a limited amount per day. Try again tomorrow.")
    if not (PADDLE_API_KEY and PADDLE_PRODUCT):
        raise Refused(503, "Top-ups aren't set up on this server yet.")
    txn = paddle("/transactions", {
        "items": [{"quantity": 1, "price": {"description": f"${amount} of Muselight credits", "name": f"${amount} Muselight credits",
                                             "product_id": PADDLE_PRODUCT, "tax_mode": "account_setting",
                                             "unit_price": {"amount": str(amount * 100), "currency_code": "USD"}}}],
        "custom_data": {"account_id": acct["id"]}, "checkout": {"url": PUBLIC_URL + "/pay"}})["data"]
    return {"checkout_url": txn["checkout"]["url"], "transaction": txn["id"]}


def verify_paddle(header, raw):
    """Paddle-Signature: ts=...;h1=... where h1 = HMAC-SHA256(secret, "ts:body"). Old (replayed) events are refused."""
    parts = dict(p.split("=", 1) for p in (header or "").split(";") if "=" in p)
    ts, sigs = parts.get("ts", ""), [p.split("=", 1)[1] for p in (header or "").split(";") if p.startswith("h1=")]
    if not (PADDLE_SECRET and ts.isdigit() and sigs) or abs(time.time() - int(ts)) > 300:
        return False
    want = hmac.new(PADDLE_SECRET.encode(), ts.encode() + b":" + raw, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(want, s) for s in sigs)


def paddle_event(ev):
    kind, d = ev.get("event_type"), ev.get("data") or {}
    if kind == "transaction.completed":
        aid = (d.get("custom_data") or {}).get("account_id")
        totals = (d.get("details") or {}).get("totals") or {}
        if not aid or totals.get("currency_code") != "USD" or not db.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
            print("paddle: transaction for an unknown account", d.get("id"), flush=True)
            return
        cents = int(totals.get("subtotal") or 0)  # before tax: tax is Paddle's to pay over, not credit
        move(aid, "topup", cents * 10_000, "paddle:" + d["id"],
             {"fee": totals.get("fee"), "earnings": totals.get("earnings"), "tax": totals.get("tax"), "customer": d.get("customer_id")})
        if d.get("customer_id"):
            try:  # the email lets you find the account again if they lose their PC
                email = paddle(f"/customers/{d['customer_id']}")["data"].get("email")
                with lock:
                    db.execute("UPDATE accounts SET email=COALESCE(email, ?) WHERE id=?", (email, aid))
            except Refused:
                pass
    elif kind in ("adjustment.created", "adjustment.updated") and d.get("status") == "approved" and d.get("action") in ("refund", "chargeback"):
        row = db.execute("SELECT account FROM ledger WHERE ref=?", ("paddle:" + str(d.get("transaction_id")),)).fetchone()
        if not row:
            return
        cents = int(((d.get("totals") or {}).get("subtotal")) or 0)
        move(row["account"], d["action"], -cents * 10_000, "paddle-adj:" + d["id"], {"reason": d.get("reason")})
        if d["action"] == "chargeback":
            with lock:
                db.execute("UPDATE accounts SET frozen=1 WHERE id=?", (row["account"],))


PAY_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Muselight credits</title><style>body{margin:0;background:#070708;color:#e8e8ea;font:15px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}
.c{max-width:420px;padding:24px;text-align:center}h1{font-size:20px;font-weight:600}p{color:#9a9aa2}</style></head>
<body><div class="c"><h1>Muselight credits</h1><p id="m">Opening the secure checkout…</p></div>
<script src="https://cdn.paddle.com/paddle/v2/paddle.js"></script>
<script>
%ENV%
Paddle.Initialize({token: %TOKEN%, eventCallback: e => {
  if (e.name === "checkout.completed") document.getElementById("m").textContent = "Paid. Your credits appear in Muselight in a few seconds. You can close this window.";
  if (e.name === "checkout.closed") document.getElementById("m").textContent = "Checkout closed. You can close this window.";
}});
</script></body></html>"""  # Paddle.js opens the checkout for the ?_ptxn= transaction in the link by itself


# ---------- reports ----------

def report(days=30):
    since = time.time() - days * 86400
    led = {r["kind"]: r for r in db.execute("SELECT kind, COUNT(*) AS n, SUM(amount) AS s FROM ledger WHERE created > ? GROUP BY kind", (since,))}
    fees = sum(float(json.loads(r["meta"]).get("fee") or 0) for r in db.execute("SELECT meta FROM ledger WHERE kind='topup' AND created > ?", (since,)))
    sources = [dict(r) for r in db.execute("""SELECT source, COUNT(*) AS runs, SUM(charged) / 1e6 AS charged, SUM(actual) AS cost,
        SUM(ref_est) AS fal_list_price, SUM(CASE WHEN actual IS NULL THEN 1 ELSE 0 END) AS unknown_cost
        FROM runs WHERE status='done' AND created > ? GROUP BY source ORDER BY charged DESC""", (since,))]
    models = [dict(r) for r in db.execute("""SELECT model, COUNT(*) AS runs, SUM(charged) / 1e6 AS charged, SUM(actual) AS cost,
        SUM(CASE WHEN actual IS NULL THEN 1 ELSE 0 END) AS unknown_cost, SUM(CASE WHEN actual * 1e6 > charged THEN 1 ELSE 0 END) AS loss_runs
        FROM runs WHERE status='done' AND created > ? GROUP BY model ORDER BY charged DESC""", (since,))]
    charged = sum(m["charged"] or 0 for m in models)
    cost = sum(m["cost"] or 0 for m in models)
    measured = [m for m in models if not m["unknown_cost"]]
    margin = sum((m["charged"] or 0) - (m["cost"] or 0) for m in measured)
    owed = db.execute("SELECT COALESCE(SUM(balance), 0) AS s FROM accounts").fetchone()["s"]
    return {"days": days, "topups": usd((led.get("topup") or {"s": 0})["s"] or 0), "paddle_fees": round(fees / 100, 2),
            "refunds_and_chargebacks": usd(-sum((led.get(k) or {"s": 0})["s"] or 0 for k in ("refund", "chargeback")) or 0),
            "chargebacks": (led.get("chargeback") or {"n": 0})["n"], "runs_charged": round(charged, 2), "cost_known": round(cost, 2),
            "margin_on_measured_runs": round(margin, 2), "credit_owed_to_users": usd(owed),
            "warning": None if FAL_ADMIN_KEY else "Set FAL_ADMIN_KEY: without it real fal costs aren't read and prices can't correct themselves.",
            "sources": sources[:50], "models": models[:50]}


# ---------- HTTP ----------

hits = {}  # (address, bucket) -> [times]


def limited(addr, bucket, n, per):
    now, key = time.time(), (addr, bucket)
    with lock:
        hits[key] = [t for t in hits.get(key, []) if now - t < per] + [now]
        return len(hits[key]) > n


class Handler(BaseHTTPRequestHandler):
    server_version = "MuselightCredits/1"

    def addr(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() if TRUST_PROXY and fwd else self.client_address[0]

    def cors(self):
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):  # the browser asks first before the web app sends a signed-in request
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise Refused(413, "Too big. Files go through /v1/uploads.")
        self.raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(self.raw) if self.raw else {}
        except ValueError:
            raise Refused(400, "Send JSON.")

    def acct(self):
        if limited(self.headers.get("Authorization", ""), "api", 300, 60):
            raise Refused(429, "Too many requests. Slow down a little.")
        return account_by_token(self.headers.get("Authorization", "").removeprefix("Bearer ").strip())

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        u = urllib.parse.urlparse(self.path)
        p = u.path.rstrip("/")
        try:
            if method == "GET" and p == "/pay":
                page = PAY_PAGE.replace("%ENV%", "" if PADDLE_LIVE else 'Paddle.Environment.set("sandbox");').replace("%TOKEN%", json.dumps(PADDLE_CLIENT_TOKEN))
                return self.send(200, page, "text/html; charset=utf-8")
            if method == "GET" and p in ("", "/health"):
                return self.send(200, {"ok": True, "models": len(prices)})
            if method == "GET" and p == "/v1/prices":
                return self.send(200, {"markup": MARKUP, "models": price_list()})
            if method == "GET" and p == "/v1/config":  # what the web app needs to show its sign-in options
                return self.send(200, {"supabase_url": SUPABASE_URL, "supabase_anon_key": SUPABASE_ANON_KEY, "telegram_bot": TELEGRAM_BOT_NAME,
                                       "terms": TERMS_URL, "min_topup": MIN_TOPUP, "max_topup": MAX_TOPUP})
            if method == "GET" and p == "/v1/schema":  # a model's settings, for the web app's form
                mid = (urllib.parse.parse_qs(u.query).get("model") or [""])[0]
                if mid not in prices:
                    raise Refused(404, "That model isn't available.")
                sch = schema_of(mid)
                return self.send(200, core.normalize(sch, sch.get("x-fal-order-properties")))
            if method == "POST" and p == "/v1/auth/telegram":
                if limited(self.addr(), "tg", 30, 3600):
                    raise Refused(429, "Too many sign-in attempts. Try again later.")
                return self.send(200, telegram_login(self.body()))
            if method == "POST" and p == "/v1/paddle":
                self.body()
                if not verify_paddle(self.headers.get("Paddle-Signature"), self.raw):
                    return self.send(401, {"error": "bad signature"})
                paddle_event(json.loads(self.raw))
                return self.send(200, {"ok": True})
            if method == "POST" and p == "/v1/accounts":
                b = self.body()
                if limited(self.addr(), "join", 10, 86400):
                    raise Refused(429, "Too many new accounts from this connection today.")
                return self.send(200, create_account(bool(b.get("accept_terms"))))
            if p == "/v1/admin/report":
                if not ADMIN_TOKEN or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + ADMIN_TOKEN):
                    raise Refused(401, "Admin only.")
                return self.send(200, report(int((urllib.parse.parse_qs(u.query).get("days") or ["30"])[0])))
            acct = self.acct()
            if method == "GET" and p == "/v1/me":
                return self.send(200, me(acct))
            if method == "POST" and p == "/v1/quote":
                b = self.body()
                return self.send(200, quote_view(b.get("model", ""), b.get("input") or {}, b.get("provider") or None))
            if method == "POST" and p == "/v1/runs":
                b = self.body()
                return self.send(200, start_run(acct, b.get("model", ""), b.get("input") or {}, b.get("provider") or None))
            if method == "GET" and p == "/v1/runs":
                q = urllib.parse.parse_qs(u.query)
                return self.send(200, {"runs": list_runs(acct, (q.get("limit") or [60])[0], (q.get("before") or [None])[0])})
            m = re.fullmatch(r"/v1/runs/(run_[0-9a-f]+)(/cancel|/delete)?", p)
            if m and method == "GET" and not m.group(2):
                return self.send(200, get_run(acct, m.group(1)))
            if m and method == "POST" and m.group(2) == "/cancel":
                return self.send(200, cancel_run(acct, m.group(1)))
            if m and method == "POST" and m.group(2) == "/delete":
                return self.send(200, hide_run(acct, m.group(1)))
            if method == "POST" and p == "/v1/uploads":  # a one-time upload link on fal's storage, for the run's input files
                b = self.body()
                if acct["balance"] <= 0 or limited(acct["id"], "upload", 300, 86400):
                    raise Refused(402 if acct["balance"] <= 0 else 429, "Top up to use Muselight Credits." if acct["balance"] <= 0 else "Upload limit reached for today.")
                up = fal("https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3",
                         {"content_type": str(b.get("content_type") or "application/octet-stream")[:100], "file_name": str(b.get("file_name") or "file")[:200]})
                return self.send(200, {"upload_url": up["upload_url"], "file_url": up["file_url"]})
            if method == "POST" and p == "/v1/topups":
                return self.send(200, start_topup(acct, self.body().get("amount")))
            raise Refused(404, "Not found.")
        except Refused as e:
            self.send(e.code, {"error": str(e)})
        except Exception as e:
            print("error:", method, p, repr(e), flush=True)
            self.send(500, {"error": "Something went wrong on the Muselight server. Nothing was charged for a run that didn't start."})

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/v1/runs/", "/health")):  # status checks would drown everything else
            print(self.addr(), fmt % args, flush=True)


# ---------- commands ----------

def selftest():
    global PADDLE_SECRET, FAL_KEY
    FAL_KEY = FAL_KEY or "test"
    PADDLE_SECRET, raw, ts = "pdl_ntfset_test", b'{"x":1}', str(int(time.time()))
    good = hmac.new(PADDLE_SECRET.encode(), ts.encode() + b":" + raw, hashlib.sha256).hexdigest()
    assert verify_paddle(f"ts={ts};h1={good}", raw) and not verify_paddle(f"ts={ts};h1={'0' * 64}", raw)
    assert not verify_paddle(f"ts={int(ts) - 3600};h1={good}", raw)  # replayed later
    a = create_account(True)
    acct = account_by_token(a["token"])
    assert move(a["account_id"], "topup", 10 * M, "test:1") and not move(a["account_id"], "topup", 10 * M, "test:1")  # a resent event counts once
    assert account_by_token(a["token"])["balance"] == 10 * M and acct["id"] == a["account_id"]
    prices["test/model"] = {"name": "t", "cat": "", "desc": "", "thumb": "", "cost": {"usd": 0.05, "per": "image"}}
    schemas["test/model"] = {"properties": {"num_images": {"default": 1}}}
    assert quote("test/model", {"num_images": 2})[0] == math.ceil(round(sell(0.10, 0.10) * 1000, 6)) * 1000
    assert sell(0.05, 0.10) == 0.10 * (1 + MARKUP) and sell(0.10, 0.10) == 0.10 * (1 + max(MARKUP, MIN_MARGIN))  # cheap source: market price
    assert middle([("fal", 0.10), ("atlas", 0.04), ("wavespeed", 0.06), ("atlas", 0.09), ("nobody", 0.01)]) == 0.06  # each big supplier once
    assert closed("fal-ai/nano-banana") and closed("fal-ai/kling-video/v2.1/pro/image-to-video") and closed("fal-ai/flux-pro/v1.1-ultra")
    assert not closed("fal-ai/flux/dev") and not closed("fal-ai/wan/v2.2-a14b/text-to-video") and closed("fal-ai/wan-25-preview/text-to-video")
    assert sell(0.038, 0.038, TIGHT_MARGIN) < sell(0.038, 0.038)
    assert trusted(0.05, 0.06) == 0.05 and abs(sell(trusted(0.001, 0.06), 0.06) - 0.06 * (1 + MARKUP)) < 1e-12  # a price-list error: market price
    global TELEGRAM_BOT_TOKEN
    TELEGRAM_BOT_TOKEN = "123:test"
    d = {"id": "42", "first_name": "Ada", "auth_date": str(int(time.time()))}
    d["hash"] = hmac.new(hashlib.sha256(b"123:test").digest(), "\n".join(f"{k}={d[k]}" for k in sorted(d)).encode(), hashlib.sha256).hexdigest()
    t = telegram_login(dict(d))["token"]
    assert account_by_token(t)["ext_id"] == "tg:42" and account_by_token(telegram_login(dict(d))["token"])["id"] == account_by_token(t)["id"]
    try:
        telegram_login(dict(d, first_name="Eve")); raise AssertionError("forged Telegram login accepted")
    except Refused:
        pass
    assert account_by_token(a["token"])["id"] == a["account_id"]  # a web session doesn't sign the desktop code out
    tg = account_by_token(t)["id"]
    db.execute("DELETE FROM sessions WHERE account=?", (tg,)); db.execute("DELETE FROM accounts WHERE id=?", (tg,))
    db.execute("DELETE FROM accounts WHERE id=?", (a["account_id"],)); db.execute("DELETE FROM ledger WHERE account=?", (a["account_id"],))
    print("credits selftest ok")


if __name__ == "__main__":
    load_prices()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "selftest":
        selftest()
    elif cmd == "prices":
        print("models priced:", refresh_prices())
    elif cmd == "report":
        print(json.dumps(report(int(sys.argv[2]) if len(sys.argv) > 2 else 30), indent=2))
    elif cmd == "token":  # someone lost their PC: find them by account id or the email Paddle has for them, issue a new sign-in token
        row = db.execute("SELECT id FROM accounts WHERE id=? OR email=?", (sys.argv[2], sys.argv[2])).fetchone()
        print(new_token(row["id"]) if row else "no such account")
    elif cmd == "credit":  # goodwill or a manual correction: python server.py credit acct_x 5 "sorry about the outage"
        print(move(sys.argv[2], "adjust", int(float(sys.argv[3]) * M), f"adjust:{time.time()}", {"note": " ".join(sys.argv[4:])}))
    else:
        if not FAL_KEY:
            sys.exit("Set FAL_KEY (see DEPLOY.md).")
        threading.Thread(target=sweeper, daemon=True).start()
        threading.Thread(target=lambda: (prices or refresh_prices(), build_catalog()), daemon=True).start()  # until then, runs go to fal
        port = int(env("PORT", "8080"))
        print(f"Muselight Credits on :{port} · {len(prices)} models · sources: {', '.join(source_ids())} · market +{MARKUP:.0%}, "
              f"cost +{MIN_MARGIN:.0%} at least · Paddle {'live' if PADDLE_LIVE else 'sandbox'}", flush=True)
        ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
