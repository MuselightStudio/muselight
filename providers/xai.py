"""xAI: Grok Imagine images and video. Shares the xAI key with the Grok assistant."""
from . import _core as core

ID, LABEL, GROUP = "xai", "xAI (Grok Imagine)", "maker"
KEYS = ["XAI_API_KEY"]
LINK, BILLING = "https://console.x.ai", "console.x.ai (Billing)"
HELP = "Grok Imagine image and video direct from xAI (the same key also powers the Grok assistant)."
API = "https://api.x.ai/v1"
call = core.caller(__name__)
ASPECTS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
IMAGE = core.S(prompt=core.T("What to make, or how to change the image."), images=core.F("image", "Images to edit (uses the edit endpoint).", 4),
               aspect_ratio=core.E(ASPECTS, "auto"), resolution=core.E(["1k", "2k"], "1k"), n=core.N(1, 10, 1, "How many images."))
VIDEO = core.S(prompt=core.T("What happens in the video."), image=core.F("image", "Optional first frame (image to video)."),
               last_frame=core.F("image", "Optional last frame."), reference_images=core.F("image", "Optional references.", 4),
               duration=core.N(1, 15, 6, "Seconds."), aspect_ratio=core.E(["16:9", "9:16", "1:1", "4:3", "3:4"], "16:9"),
               resolution=core.E(["480p", "720p", "1080p"], "720p"))


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    rows = call(f"{API}/models").get("data", [])
    return [{"id": m["id"], "name": m["id"], "cat": "video" if "video" in m["id"] else "image", "desc": "xAI"}
            for m in rows if "imagine" in m["id"] or "image" in m["id"]]


def schema(mid):
    return VIDEO if "video" in mid else IMAGE


def run(mid, body, job):
    if "video" not in mid:
        imgs = body.pop("images", None)
        if imgs:
            r = call(f"{API}/images/edits", {"model": mid, **body, "image": {"url": imgs[0], "type": "image_url"},
                                             **({"images": [{"url": u, "type": "image_url"} for u in imgs]} if len(imgs) > 1 else {})}, timeout=600)
        else:
            r = call(f"{API}/images/generations", {"model": mid, **body}, timeout=600)
        return r, core.media_urls(r.get("data"), "data")
    for k in ("image", "last_frame"):
        if body.get(k):
            body[k] = {"url": body[k]}
    if body.get("reference_images"):
        body["reference_images"] = [{"url": u} for u in body["reference_images"]]
    d = call(f"{API}/videos/generations", {"model": mid, **body})
    job["request_id"] = d.get("request_id")

    def check():
        r = call(f"{API}/videos/{d['request_id']}")
        if r.get("status") == "done":
            return r, core.media_urls(r.get("video"), "video")
        if r.get("status") in ("failed", "expired"):
            raise RuntimeError(f"xAI: {r.get('error') or r.get('status')}")
    return core.wait(job, check, LABEL, every=4)


def test():
    return f"Connected · {len(models())} Grok Imagine models"
