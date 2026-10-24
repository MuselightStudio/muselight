"""Atlas Cloud: a public model list with prices, and an OpenAPI file per model."""
import json, urllib.error, urllib.request
from . import _core as core

ID, LABEL, GROUP = "atlas", "Atlas Cloud", "market"
KEYS = ["ATLASCLOUD_API_KEY"]
LINK, BILLING = "https://www.atlascloud.ai/console/api-keys", "atlascloud.ai/console/billing"
HELP = "Discounted prices on many image and video models. Its models show prices."
FILES = "upload"
API = "https://api.atlascloud.ai/api/v1"
call = core.caller(__name__)
info, uploaded = {}, {}  # model -> {schema, path, schema_url}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    out = []
    for m in sorted(core.unwrap(call(f"{API}/models")), key=lambda m: -(m.get("priority") or 0)):
        if m.get("type") == "Text":
            continue  # chat models, not generation
        info.setdefault(m["model"], {})["schema_url"] = m.get("schema")
        out.append({"id": m["model"], "name": m.get("displayName") or m["model"], "cat": (m.get("categories") or [m.get("type", "")])[0].lower(),
                    "desc": (m.get("profile") or "")[:200], "thumb": m.get("coverUrl") or "",
                    "price": core.price(((m.get("price") or {}).get("actual") or {}).get("base_price")),
                    "cost": core.cost(((m.get("price") or {}).get("actual") or {}).get("base_price"),
                                      ((m.get("price") or {}).get("actual") or {}).get("unit") or ("second" if m.get("type") == "Video" else "run"))})
    return out


def schema(mid):
    entry = info.setdefault(mid, {})
    if "schema" not in entry:
        url = entry.get("schema_url") or "https://static.atlascloud.ai/model/schema/" + mid.replace("/", "-") + ".json"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": core.UA}), timeout=30) as r:
                spec = json.load(r)
        except urllib.error.HTTPError:
            raise RuntimeError(f"Atlas Cloud has no input schema for '{mid}'.")
        path = next((p for p, v in spec.get("paths", {}).items() if "post" in v), None)
        variants = core.openapi_variants(spec, path) if path else []
        if not variants:
            raise RuntimeError(f"Atlas Cloud has no input schema for '{mid}'.")
        entry.update(schema=core.normalize(variants[0][1]), path=path)
    return entry["schema"]


def upload(path):
    k = (str(path), path.stat().st_mtime)
    if k not in uploaded:
        data, ctype = core.multipart({}, [("file", path)])
        d = core.unwrap(call(f"{API}/model/uploadMedia", data=data, ctype=ctype, timeout=300))
        uploaded[k] = d.get("download_url") or d.get("url")
    return uploaded[k]


def quote(mid, body):
    """Atlas Cloud's own price for these exact settings, after your discount (nothing runs or is charged)."""
    return core.unwrap(call(f"{API}/model/calculate", {"model": mid, **body}, timeout=60)).get("price")


def run(mid, body, job):
    schema(mid)  # learns which endpoint this model uses
    d = core.unwrap(call("https://api.atlascloud.ai" + info[mid]["path"], {"model": mid, **body}))
    job["request_id"] = d["id"]

    def check():
        r = core.unwrap(call(f"{API}/model/prediction/{d['id']}"))
        status = str(r.get("status", "")).lower()
        if status in ("completed", "succeeded"):
            return r, core.media_urls(r.get("outputs"), "outputs")
        if status in ("failed", "cancelled", "canceled"):
            raise RuntimeError(f"Atlas Cloud: {r.get('error') or status}")
    return core.wait(job, check, LABEL)


def test():
    try:
        call(f"{API}/model/prediction/key-check")
    except RuntimeError as e:
        if "didn't accept your key" in str(e):
            raise
    return "Connected to Atlas Cloud"
