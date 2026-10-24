"""PiAPI: one task API for Seedance, Kling, Hailuo, Nano Banana, Sora, FLUX and more.
Its models and settings come from the bundled catalog (tools/build_catalogs.py refreshes it)."""
from . import _core as core

ID, LABEL, GROUP = "piapi", "PiAPI", "market"
KEYS = ["PIAPI_API_KEY"]
LINK, BILLING = "https://piapi.ai/workspace/key", "piapi.ai/workspace/billing"
HELP = "Pay-as-you-go access to Kling, Seedance, Hailuo, Nano Banana, Sora and more, often with cheaper modes."
API = "https://api.piapi.ai/api/v1"
call = core.caller(__name__)
CAT = core.catalog("piapi")


def headers():
    return {"x-api-key": core.key(KEYS[0])}


def models():
    return [{"id": mid, "name": r["name"], "cat": r["cat"] or "image", "desc": r.get("desc", "")} for mid, r in CAT.items()]


def schema(mid):
    if mid not in CAT:
        raise RuntimeError(f"PiAPI has no model called '{mid}' in this app's list.")
    return core.normalize(CAT[mid]["schema"])


def run(mid, body, job):
    r = CAT[mid]
    d = core.unwrap(call(f"{API}/task", {"model": r["model"], "task_type": r["task_type"], "input": body}))
    job["request_id"] = d.get("task_id")

    def check():
        t = core.unwrap(call(f"{API}/task/{d['task_id']}"))
        st = str(t.get("status", "")).lower()
        if st == "completed":
            return t, core.media_urls(t.get("output"), "output")
        if st == "failed":
            err = t.get("error") or {}
            raise RuntimeError(f"PiAPI: {err.get('message') or err.get('raw_message') or 'the task failed'}")
    return core.wait(job, check, LABEL, every=3)


def test():
    try:
        call(f"{API}/task/key-check")
    except RuntimeError as e:
        if "didn't accept your key" in str(e):
            raise
    return "Connected to PiAPI"
