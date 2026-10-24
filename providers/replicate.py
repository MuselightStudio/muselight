"""Replicate: official models listed; any model works by its owner/name."""
from . import _core as core

ID, LABEL, GROUP = "replicate", "Replicate", "market"
KEYS = ["REPLICATE_API_TOKEN"]
LINK, BILLING = "https://replicate.com/account/api-tokens", "replicate.com/account/billing"
HELP = "Its official models are listed; type replicate:owner/name in a model box for any other model."
API = "https://api.replicate.com/v1"
call = core.caller(__name__)
info = {}  # model -> {schema, version}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    # ponytail: only Replicate's "official" collection is listed (its full catalogue is tens of thousands of models);
    # any other model works by typing replicate:owner/name in the picker.
    return [{"id": f"{m['owner']}/{m['name']}", "name": f"{m['owner']}/{m['name']}", "cat": "official", "desc": (m.get("description") or "")[:200],
             "thumb": m.get("cover_image_url") or "", "date": (m.get("latest_version") or {}).get("created_at", "")}
            for m in call(f"{API}/collections/official").get("models", [])]


def schema(mid):
    if mid not in info:
        v = call(f"{API}/models/{mid}").get("latest_version") or {}
        comps = (v.get("openapi_schema") or {}).get("components", {}).get("schemas", {})
        if "Input" not in comps:
            raise RuntimeError(f"Replicate has no input schema for '{mid}'.")
        inp = core.resolve(comps["Input"], comps)
        order = sorted(inp.get("properties", {}), key=lambda k: inp["properties"][k].get("x-order", 99))
        info[mid] = {"schema": core.normalize(inp, order), "version": v.get("id")}
    return info[mid]["schema"]


def run(mid, body, job):
    schema(mid)
    d = call(f"{API}/predictions", {"version": info[mid]["version"], "input": body})
    job["request_id"] = d.get("id")

    def check():
        r = call(d["urls"]["get"])
        if r.get("status") == "succeeded":
            return r, core.media_urls(r.get("output"), "output")
        if r.get("status") in ("failed", "canceled"):
            raise RuntimeError(f"Replicate: {r.get('error') or r.get('status')}")
    return core.wait(job, check, LABEL, cancel=lambda: call(d["urls"]["cancel"], data=b"", method="POST"))


def test():
    return f"Connected as {call(f'{API}/account').get('username', 'you')}"
