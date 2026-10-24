"""SiliconFlow: FLUX, Qwen Image and Wan at low prices. Settings come from the bundled catalog."""
from . import _core as core

ID, LABEL, GROUP = "siliconflow", "SiliconFlow", "market"
KEYS = ["SILICONFLOW_API_KEY"]
LINK, BILLING = "https://cloud.siliconflow.com/account/ak", "cloud.siliconflow.com/expensebill"
HELP = "Low-cost FLUX, Qwen Image and Wan video. Also a cheap option for the assistant."
API = "https://api.siliconflow.com/v1"
call = core.caller(__name__)
CAT = core.catalog("siliconflow")


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    return [{"id": mid, "name": mid.split("/")[-1], "cat": r["cat"], "desc": r.get("desc", "")} for mid, r in CAT.items()]


def schema(mid):
    if mid not in CAT:
        raise RuntimeError(f"SiliconFlow has no model called '{mid}' in this app's list.")
    return core.normalize(CAT[mid]["schema"])


def run(mid, body, job):
    if CAT[mid]["path"].endswith("/video/submit"):
        rid = call(f"{API}/video/submit", {"model": mid, **body})["requestId"]
        job["request_id"] = rid

        def check():
            r = call(f"{API}/video/status", {"requestId": rid})
            if r.get("status") == "Succeed":
                return r, core.media_urls(r.get("results"), "results")
            if r.get("status") == "Failed":
                raise RuntimeError(f"SiliconFlow: {r.get('reason') or 'the video failed'}")
        return core.wait(job, check, LABEL, every=4)
    r = call(f"{API}/images/generations", {"model": mid, **body}, timeout=600)
    return r, core.media_urls(r.get("images") or r.get("data"), "images")


def test():
    d = core.unwrap(call(f"{API}/user/info"))
    return f"Connected · balance {d.get('totalBalance') or d.get('balance') or '?'}"
