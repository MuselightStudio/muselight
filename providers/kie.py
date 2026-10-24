"""Kie.ai: discounted access to Veo, Seedance, Kling, Nano Banana, Suno and more through one task API.
Its models and settings come from the bundled catalog (tools/build_catalogs.py refreshes it)."""
import json
from . import _core as core

ID, LABEL, GROUP = "kie", "Kie.ai", "market"
KEYS = ["KIE_API_KEY"]
LINK, BILLING = "https://kie.ai/api-key", "kie.ai/billing"
HELP = "Often the cheapest way to run Veo, Seedance, Kling, Nano Banana, Sora and Suno."
FILES = "upload"  # wants links, so local files are uploaded to Kie's file storage first
API, FILES_API = "https://api.kie.ai/api/v1", "https://kieai.redpandaai.co/api"
call = core.caller(__name__)
CAT = core.catalog("kie")
uploaded = {}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    return [{"id": mid, "name": r["name"], "cat": r["cat"], "desc": r.get("desc", "")} for mid, r in CAT.items()]


def schema(mid):
    if mid not in CAT:
        raise RuntimeError(f"Kie.ai has no model called '{mid}' in this app's list.")
    return core.normalize(CAT[mid]["schema"])


def upload(path):
    k = (str(path), path.stat().st_mtime)
    if k not in uploaded:
        d = core.unwrap(call(f"{FILES_API}/file-base64-upload", {"base64Data": core.datauri(path), "uploadPath": "muselight", "fileName": path.name},
                             timeout=300))
        uploaded[k] = d.get("downloadUrl") or d.get("fileUrl") or d.get("url")
    return uploaded[k]


def run(mid, body, job):
    d = core.unwrap(call(f"{API}/jobs/createTask", {"model": mid, "input": body}))
    job["request_id"] = d["taskId"]

    def check():
        r = core.unwrap(call(f"{API}/jobs/recordInfo?taskId={d['taskId']}"))
        if r.get("state") == "success":
            res = r.get("resultJson")
            res = json.loads(res) if isinstance(res, str) and res else (res or {})
            return r, core.media_urls(res, "resulturls")
        if r.get("state") == "fail":
            raise RuntimeError(f"Kie.ai: {r.get('failMsg') or r.get('failCode') or 'the task failed'}")
    return core.wait(job, check, LABEL, every=3)


def test():
    return f"Connected · {core.unwrap(call(f'{API}/chat/credit'))} credits"
