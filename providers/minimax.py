"""MiniMax: Hailuo video and image-01 straight from the maker. Hailuo H3 is set up here by hand; the older models
come from the bundled catalog."""
import json
from . import _core as core

ID, LABEL, GROUP = "minimax", "MiniMax (Hailuo)", "maker"
KEYS = ["MINIMAX_API_KEY"]
LINK, BILLING = "https://platform.minimax.io/user-center/basic-information/interface-key", "platform.minimax.io (Billing)"
HELP = "Hailuo video (H3, 2.3) and image-01 direct from MiniMax."
API = "https://api.minimax.io"
call = core.caller(__name__)
CAT = core.catalog("minimax")
H3 = {"MiniMax-H3": ["768P", "2K"], "MiniMax-H3-Max": ["480P", "768P"]}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    out = [{"id": m, "name": m, "cat": "video", "desc": "Hailuo H3: text, first/last frame or reference images to video, with sound."} for m in H3]
    return out + [{"id": mid, "name": mid, "cat": r["cat"], "desc": r.get("desc", "")} for mid, r in CAT.items()]


def schema(mid):
    if mid in H3:
        return core.S(prompt=core.T("What happens in the video."), first_frame=core.F("image", "Optional first frame."),
                      last_frame=core.F("image", "Optional last frame."), reference_images=core.F("image", "Optional people, products or styles to keep.", 9),
                      resolution=core.E(H3[mid], H3[mid][-1]), duration=core.N(4 if mid == "MiniMax-H3" else 5, 15, 5, "Seconds."))
    if mid not in CAT:
        raise RuntimeError(f"MiniMax has no model called '{mid}' in this app's list.")
    s = core.normalize(CAT[mid]["schema"])
    if "subject_reference" in s["properties"]:
        s["properties"]["subject_reference"] = core.F("image", "Picture of the character to keep.", 1)
    return s


def _check_base(r):
    base = r.get("base_resp") or {}
    if base.get("status_code") not in (None, 0):
        code = {1004: 401, 2049: 401, 1008: 402, 1002: 429, 1026: 400, 2013: 400}.get(base["status_code"], 500)  # MiniMax's own codes
        raise RuntimeError(core.api_error(LABEL, BILLING, code, json.dumps({"message": base.get("status_msg")})))
    return r


def run(mid, body, job):
    if mid in H3:
        content = [{"type": "text", "text": body.get("prompt", "")}]
        for role in ("first_frame", "last_frame"):
            if body.get(role):
                content.append({"type": "image_url", "image_url": {"url": body[role]}, "role": role})
        content += [{"type": "image_url", "image_url": {"url": u}, "role": "reference_image"} for u in body.get("reference_images") or []]
        d = call(f"{API}/v2/video_generation", {"model": mid, "content": content, "resolution": body.get("resolution", H3[mid][-1]),
                                                 "duration": body.get("duration", 5)})
        d = d.get("task") or d
        tid = d.get("id") or d.get("task_id")
        job["request_id"] = tid

        def check():
            r = call(f"{API}/v2/query/video_generation/{tid}")
            t = r.get("task") or r
            if t.get("status") == "succeeded":
                return r, core.media_urls(t.get("content"), "content")
            if t.get("status") == "failed":
                raise RuntimeError(f"MiniMax: {t.get('error') or (t.get('base_resp') or {}).get('status_msg') or 'the video failed'}")
        return core.wait(job, check, LABEL, every=5)
    path = CAT[mid]["path"]
    if "subject_reference" in body:
        refs = body.pop("subject_reference")
        body["subject_reference"] = [{"type": "character", "image_file": u} for u in (refs if isinstance(refs, list) else [refs])]
    d = _check_base(call(API + path, {"model": mid.split("@")[0], **body}, timeout=600))
    if "image" in path:
        return d, core.media_urls(d.get("data"), "image_urls")
    tid = d["task_id"]
    job["request_id"] = tid

    def check():
        r = _check_base(call(f"{API}/v1/query/video_generation?task_id={tid}"))
        if r.get("status") == "Success":
            f = _check_base(call(f"{API}/v1/files/retrieve?file_id={r['file_id']}"))
            return r, [f["file"]["download_url"]]
        if r.get("status") == "Fail":
            raise RuntimeError("MiniMax: the video failed")
    return core.wait(job, check, LABEL, every=5)


def test():
    try:
        _check_base(call(f"{API}/v1/query/video_generation?task_id=0"))
    except RuntimeError as e:
        if "didn't accept your key" in str(e) or "1004" in str(e) or "auth" in str(e).lower():
            raise
    return "Connected to MiniMax"
