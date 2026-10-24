"""WaveSpeedAI: one call lists every model with its settings schema and price."""
from . import _core as core

ID, LABEL, GROUP = "wavespeed", "WaveSpeedAI", "market"
KEYS = ["WAVESPEED_API_KEY"]
LINK, BILLING = "https://wavespeed.ai/accesskey", "wavespeed.ai/top-up"
HELP = "Often cheaper for popular video models (Wan, Seedance, Kling). Its models show prices."
FILES = "upload"  # wants links, so local files are uploaded first
API = "https://api.wavespeed.ai/api/v3"
call = core.caller(__name__)
schemas, uploaded = {}, {}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    if not core.key(KEYS[0]):
        return public_models()
    out = []
    for m in core.unwrap(call(f"{API}/models")):
        for s in (m.get("api_schema") or {}).get("api_schemas", []):
            if s.get("type") == "model_run":
                schemas[m["model_id"]] = core.normalize({"type": "object", **(s.get("request_schema") or {})})
        out.append({"id": m["model_id"], "name": m.get("name") or m["model_id"], "cat": m.get("type", ""),
                    "desc": (m.get("description") or "")[:200], "price": core.price(m.get("base_price")),
                    "cost": core.cost(m.get("base_price"), "clip" if "video" in m.get("type", "") else "run")})
    return out


def public_models():
    """Without a key: WaveSpeed's public catalogue, for price comparisons (prices there are in millionths of a dollar)."""
    import json, urllib.request
    out, page = [], 1
    while page < 20:
        req = urllib.request.Request(f"https://wavespeed.ai/api/models?page={page}&page_size=200", headers={"User-Agent": core.UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        for m in d.get("items", []):
            usd = (m.get("base_price") or 0) / 1e6 * (m.get("discount_rate") or 100) / 100
            out.append({"id": m["model_uuid"], "name": m.get("model_name") or m["model_uuid"], "cat": m.get("type", ""),
                        "desc": (m.get("description") or "")[:200], "thumb": m.get("poster") or "", "price": core.price(usd), "cost": core.cost(usd, "clip" if "video" in m.get("type", "") else "run")})
        if page * 200 >= (d.get("total") or 0):
            break
        page += 1
    return out


def schema(mid):
    if mid not in schemas:
        models()  # one call returns every model's schema
    if mid not in schemas:
        raise RuntimeError(f"WaveSpeed has no model called '{mid}'." if core.key(KEYS[0]) else
                           "WaveSpeed only shows a model's settings to connected accounts. Add a WaveSpeed key in Connections.")
    return schemas[mid]


def upload(path):
    k = (str(path), path.stat().st_mtime)
    if k not in uploaded:
        data, ctype = core.multipart({}, [("file", path)])
        uploaded[k] = core.unwrap(call(f"{API}/media/upload/binary", data=data, ctype=ctype, timeout=300))["download_url"]
    return uploaded[k]


def quote(mid, body):
    """WaveSpeed's own price for these exact settings (media included), after your account's discount."""
    d = core.unwrap(call(f"{API}/model/price", {"model_id": mid, "inputs": body}, timeout=60))
    return d.get("discounted_price") or d.get("price")


def run(mid, body, job):
    d = core.unwrap(call(f"{API}/{mid}", body))
    job["request_id"] = d["id"]

    def check():
        r = core.unwrap(call(f"{API}/predictions/{d['id']}/result"))
        status = str(r.get("status", "")).lower()
        if status == "completed":
            return r, core.media_urls(r.get("outputs"), "outputs")
        if status in ("failed", "cancelled", "timeout", "deleted"):
            raise RuntimeError(f"WaveSpeed: {r.get('error') or status}")
    return core.wait(job, check, LABEL)


def test():
    return f"Connected · balance ${core.unwrap(call(f'{API}/balance')).get('balance', 0):.2f}"
