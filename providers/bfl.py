"""Black Forest Labs: FLUX straight from its makers. Their OpenAPI file lists every model and its settings."""
import json, urllib.request
from . import _core as core

ID, LABEL, GROUP = "bfl", "Black Forest Labs (FLUX)", "maker"
KEYS = ["BFL_API_KEY"]
LINK, BILLING = "https://dashboard.bfl.ai/keys", "dashboard.bfl.ai"
HELP = "FLUX direct from its makers, often first with new FLUX versions and tools (expand, fill, erase, try-on)."
API, SPEC = "https://api.bfl.ai", "https://api.bfl.ai/openapi.json"
call = core.caller(__name__)
spec = {}


def headers():
    return {"x-key": core.key(KEYS[0])}


def _spec():
    if not spec:
        with urllib.request.urlopen(urllib.request.Request(SPEC, headers={"User-Agent": core.UA}), timeout=60) as r:
            spec.update(json.load(r))
    return spec


def models():
    out = []
    for path, ops in _spec().get("paths", {}).items():
        post = ops.get("post")
        if not post or "finetune" in path or not path.startswith("/v1/flux"):
            continue
        mid = path[len("/v1/"):]
        out.append({"id": mid, "name": post.get("summary") or mid, "cat": "video" if "video" in mid else "image", "desc": (post.get("description") or "")[:200]})
    return out


def schema(mid):
    variants = core.openapi_variants(_spec(), "/v1/" + mid)
    if not variants:
        raise RuntimeError(f"Black Forest Labs has no model called '{mid}'.")
    return core.normalize(variants[0][1])


def run(mid, body, job):
    # images go as plain base64 or links
    body = {k: (v.split(",", 1)[1] if isinstance(v, str) and v.startswith("data:") else v) for k, v in body.items()}
    d = call(f"{API}/v1/{mid}", body)
    job["request_id"] = d.get("id")

    def check():
        r = call(d.get("polling_url") or f"{API}/v1/get_result?id={d['id']}")
        st = r.get("status")
        if st == "Ready":
            return r, core.media_urls(r.get("result"), "result")
        if st in ("Error", "Failed", "Content Moderated", "Request Moderated", "Task not found"):
            raise RuntimeError(f"Black Forest Labs: {st}" + (f" ({r.get('details')})" if r.get("details") else ""))
    return core.wait(job, check, LABEL, every=1.5)


def test():
    return f"Connected · {call(f'{API}/v1/credits').get('credits', '?')} credits"
