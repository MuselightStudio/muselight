"""Runway: Gen-4.5 and the other models Runway resells, from Runway's OpenAPI file (one schema per model)."""
import json, urllib.request
from . import _core as core

ID, LABEL, GROUP = "runway", "Runway", "maker"
KEYS = ["RUNWAYML_API_SECRET"]
LINK, BILLING = "https://dev.runwayml.com", "dev.runwayml.com (Billing)"
HELP = "Runway's Gen-4.5 video and Gen-4 image models, plus Kling, Seedance, Veo-style and other models through one Runway account."
API, SPEC = "https://api.dev.runwayml.com", "https://docs.dev.runwayml.com/openapi.json"
PATHS = ("/v1/image_to_video", "/v1/text_to_video", "/v1/text_to_image", "/v1/video_to_video", "/v1/image_upscale", "/v1/video_upscale")
call = core.caller(__name__)
spec, info = {}, {}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0]), "X-Runway-Version": "2024-11-06"}


def _variants():
    if not info:
        with urllib.request.urlopen(urllib.request.Request(SPEC, headers={"User-Agent": core.UA}), timeout=60) as r:
            spec.update(json.load(r))
        for path in PATHS:
            for mid, sch in core.openapi_variants(spec, path):
                if mid:
                    info.setdefault(mid, []).append((path, sch))  # some models have several endpoints (text to video, image to video)
    return info


def models():
    return [{"id": mid, "name": mid, "cat": " / ".join(p.split("/")[-1].replace("_", "-") for p, _ in v)} for mid, v in sorted(_variants().items())]


def schema(mid):
    if mid not in _variants():
        raise RuntimeError(f"Runway has no model called '{mid}'.")
    variants = _variants()[mid]
    props = {k: p for _, s in reversed(variants) for k, p in (s.get("properties") or {}).items()}
    required = set.intersection(*[set(s.get("required") or []) for _, s in variants])
    return core.normalize({"type": "object", "properties": props, "required": sorted(required)}, [k for _, s in variants for k in s.get("properties", {})])


def run(mid, body, job):
    # the endpoint whose settings cover what was filled in (e.g. a start image means image to video)
    path, raw = next(((p, s) for p, s in _variants()[mid] if set(s.get("required") or []) <= set(body) and set(body) <= set(s.get("properties") or {})),
                     _variants()[mid][0])
    props = raw.get("properties", {})
    payload = {"model": mid}
    for k, v in body.items():
        p = props.get(k, {})
        items = (p.get("items") or {}) if p.get("type") == "array" else {}
        if isinstance(v, list) and "uri" in (items.get("properties") or {}):
            v = [x if isinstance(x, dict) else {"uri": x} for x in v]  # [{uri}] objects
        payload[k] = v
    d = call(API + path, payload)
    job["request_id"] = d.get("id")

    def check():
        r = call(f"{API}/v1/tasks/{d['id']}")
        if r.get("status") == "SUCCEEDED":
            return r, [u for u in r.get("output") or [] if isinstance(u, str)]
        if r.get("status") in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Runway: {r.get('failure') or r.get('failureCode') or r.get('status')}")
    return core.wait(job, check, LABEL, cancel=lambda: call(f"{API}/v1/tasks/{d['id']}", method="DELETE"), every=3)


def test():
    org = call(f"{API}/v1/organization")
    return f"Connected · {org.get('creditBalance', '?')} credits"
