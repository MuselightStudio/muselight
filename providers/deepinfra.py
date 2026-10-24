"""DeepInfra: a public model list where every model publishes its settings; runs return the result directly."""
import json, urllib.request
from . import _core as core

ID, LABEL, GROUP = "deepinfra", "DeepInfra", "market"
KEYS = ["DEEPINFRA_API_KEY"]
LINK, BILLING = "https://deepinfra.com/dash/api_keys", "deepinfra.com/dash/billing"
HELP = "Low prices on open image and video models (FLUX, Qwen Image, Wan) and some big-name ones. Also a cheap option for the assistant."
API = "https://api.deepinfra.com"
TYPES = ("text-to-image", "text-to-video", "image-to-video", "image-to-image")
call = core.caller(__name__)
schemas = {}


def headers():
    return {"Authorization": "bearer " + core.key(KEYS[0])}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": core.UA}), timeout=60) as r:
        return json.load(r)


def _cost(p):
    p = p or {}
    if p.get("cents_per_image_unit"):
        return core.cost(p["cents_per_image_unit"] / 100, "image")
    for k in ("cents_per_output_sec", "cents_per_sec"):
        if p.get(k):
            return core.cost(p[k] / 100, "second")
    return None


def _price(p):
    p = p or {}
    if p.get("short"):
        return p["short"]
    for k, unit in (("cents_per_image_unit", "image"), ("cents_per_output_sec", "second"), ("cents_per_sec", "second")):
        if p.get(k):
            return f"${p[k] / 100:.4f}".rstrip("0").rstrip(".") + f" per {unit}"
    return ""


def models():
    return [{"id": m["model_name"], "name": m["model_name"].split("/")[-1], "cat": m["type"], "desc": (m.get("description") or "")[:200],
             "thumb": m.get("cover_img_url") or "", "price": _price(m.get("pricing")), "date": m.get("create_ts", ""), "cost": _cost(m.get("pricing"))}
            for m in _get(f"{API}/models/list") if m.get("type") in TYPES and not m.get("deprecated") and not m.get("private")]


def schema(mid):
    if mid not in schemas:
        m = _get(f"{API}/models/{mid}")
        schemas[mid] = core.normalize(m.get("in_schema") or {})
    return schemas[mid]


def run(mid, body, job):
    # ponytail: DeepInfra answers in one long request, so Cancel takes effect only once it returns
    r = call(f"{API}/v1/inference/{mid}", body, timeout=1800)
    if job["status"] == "cancelled":
        return None
    status = (r.get("inference_status") or {}).get("status")
    if status == "failed":
        raise RuntimeError(f"DeepInfra: {r.get('error') or 'the run failed'}")
    return r, core.media_urls({k: v for k, v in r.items() if k != "inference_status"}, "output")


def charged(result):
    return (result.get("inference_status") or {}).get("cost") or None


def test():
    me = call(f"{API}/v1/me")
    return f"Connected to DeepInfra as {me.get('email') or me.get('name') or 'you'}"
