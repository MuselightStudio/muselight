"""Segmind: 700+ models in a live catalog that carries each model's settings."""
import json, urllib.request
from . import _core as core

ID, LABEL, GROUP = "segmind", "Segmind", "market"
KEYS = ["SEGMIND_API_KEY"]
LINK, BILLING = "https://platform.segmind.com/api-keys", "platform.segmind.com/billing"
HELP = "700+ image, video and audio models with low average prices, including open models few others host."
API, CATALOG = "https://api.segmind.com", "https://api.spotprod.segmind.com/inference-model-information/list"
SKIP = {"textToText", "imageToText", "audioToText", "textToEmbed", "videoToText", "imageToData"}
call = core.caller(__name__)
catalog = {}


def headers():
    return {"x-api-key": core.key(KEYS[0])}


def _load():
    if not catalog:
        with urllib.request.urlopen(urllib.request.Request(CATALOG, headers={"User-Agent": core.UA}), timeout=120) as r:
            for m in json.load(r).get("Inference Model Information List", []):
                if not m.get("is_depreciated") and m.get("is_visible", True) and not m.get("coming_soon") and m.get("type") not in SKIP:
                    catalog[m["slug"]] = m
    return catalog


def models():
    return [{"id": slug, "name": m.get("title") or slug, "cat": core.snake(m.get("type") or "").replace("_", "-"), "desc": (m.get("description") or "")[:200],
             "thumb": m.get("thumbnail_image") or "", "price": f"about {core.price(m['average_cost'])} per run" if m.get("average_cost") else "",
             "date": m.get("created_at", ""), "cost": core.cost(m.get("average_cost"), "clip" if "Video" in (m.get("type") or "") else "run")}
            for slug, m in sorted(_load().items(), key=lambda kv: -(kv[1].get("popularity_score") or 0))]


def schema(mid):
    m = _load().get(mid)
    if not m:
        raise RuntimeError(f"Segmind has no model called '{mid}'.")
    s = m.get("parameters_schema") or {}
    order = sorted(s.get("properties", {}), key=lambda k: ((s["properties"][k].get("x-ui-metadata") or {}).get("order", 99)))
    return core.normalize(s, order)


def run(mid, body, job):
    d = call(f"{API}/v2/{mid}", body)
    job["request_id"] = d.get("request_id")

    def check():
        st = call(d["status_url"])
        if st.get("status") == "COMPLETED":
            r = call(d["response_url"], timeout=300)
            if isinstance(r, tuple):  # some models answer with the file itself
                return {"request_id": d.get("request_id")}, [core.bytes_uri(*r)]
            return r, core.media_urls({k: v for k, v in r.items() if k not in ("prompt", "metrics", "timings")}, "output")
        if st.get("status") in ("FAILED", "CANCELLED", "ERROR"):
            raise RuntimeError(f"Segmind: {st.get('error') or st.get('message') or st.get('status')}")
    return core.wait(job, check, LABEL, every=2.5)


def charged(result):
    return (result.get("metrics") or {}).get("cost")


def test():
    r = call(f"{API}/v1/get-user-credits")
    credits = r.get("credits") if isinstance(r, dict) else None
    return "Connected to Segmind" + (f" · {credits} credits" if credits is not None else "")
