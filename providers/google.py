"""Google Gemini API: Nano Banana image models and Gemini Omni video, through the Interactions API."""
from . import _core as core

ID, LABEL, GROUP = "google", "Google Gemini", "maker"
KEYS = ["GEMINI_API_KEY"]
LINK, BILLING = "https://aistudio.google.com/apikey", "aistudio.google.com (Billing)"
HELP = "Nano Banana image models and Gemini Omni video direct from Google. Free tier keys work for some models."
API = "https://generativelanguage.googleapis.com/v1beta"
call = core.caller(__name__)
ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"]
IMAGE = core.S(prompt=core.T("What to make, or how to change the images."), images=core.F("image", "Images to edit or use as references.", 14),
               aspect_ratio=core.E(ASPECTS), image_size=core.E(["1K", "2K", "4K"], None, "Output size."))
VIDEO = core.S(prompt=core.T("What happens in the video."), images=core.F("image", "First frame, or first and last frame, or references.", 4),
               aspect_ratio=core.E(["16:9", "9:16"]), resolution=core.E(["360p", "720p", "1080p", "4k"], "720p"))


def headers():
    return {"x-goog-api-key": core.key(KEYS[0])}


def _video(mid):
    return "omni" in mid or "veo" in mid or "video" in mid


def models():
    out = []
    for m in call(f"{API}/models?pageSize=1000").get("models", []):
        mid = m["name"].split("/", 1)[-1]
        if ("image" in mid and "embedding" not in mid) or "nano-banana" in mid or _video(mid):
            out.append({"id": mid, "name": m.get("displayName") or mid, "cat": "video" if _video(mid) else "image", "desc": (m.get("description") or "")[:200]})
    return out


def schema(mid):
    return VIDEO if _video(mid) else IMAGE


def _part(uri):
    payload, mime, _ = core.uri_bytes(uri)
    return {"type": "image", "data": __import__("base64").b64encode(payload).decode(), "mime_type": mime or "image/png"}


def run(mid, body, job):
    parts = [{"type": "text", "text": body.get("prompt", "")}] + [_part(u) for u in body.get("images") or []]
    fmt = {"type": "video" if _video(mid) else "image", **{k: body[k] for k in ("aspect_ratio", "image_size", "resolution") if body.get(k)}}
    # ponytail: one long request (Google answers when the image or video is ready), so Cancel takes effect only once it returns
    r = call(f"{API}/interactions", {"model": mid, "input": parts, "response_format": fmt}, timeout=1200)
    if job["status"] == "cancelled":
        return None
    if r.get("status") not in (None, "completed"):
        raise RuntimeError(f"Google: {r.get('error') or r.get('status')}")
    outs = [core.bytes_uri(__import__("base64").b64decode(c["data"]), c.get("mime_type")) if c.get("data") else c.get("uri")
            for step in r.get("steps", []) if step.get("type") == "model_output" for c in step.get("content", [])
            if c.get("type") in ("image", "video") and (c.get("data") or c.get("uri"))]
    if not outs:
        text = " ".join(c.get("text", "") for s in r.get("steps", []) if s.get("type") == "model_output" for c in s.get("content", []))
        raise RuntimeError(f"Google returned no {fmt['type']}" + (f": {text[:300]}" if text.strip() else " (it may have been blocked by safety filters)."))
    return core.scrub(r), outs


def test():
    n = len(models())
    return f"Connected · {n} image and video models"
