"""OpenAI: GPT Image models (and Sora video where the account has it). Shares the OpenAI key with the assistant."""
import base64
from . import _core as core

ID, LABEL, GROUP = "openai", "OpenAI (GPT Image)", "maker"
KEYS = ["OPENAI_API_KEY"]
LINK, BILLING = "https://platform.openai.com/api-keys", "platform.openai.com/settings/organization/billing"
HELP = "GPT Image models direct from OpenAI (the same key also powers the ChatGPT assistant). Needs a verified organization."
API = "https://api.openai.com/v1"
call = core.caller(__name__)
IMAGE = core.S(prompt=core.T("What to make, or how to change the images."), images=core.F("image", "Images to edit or combine (uses the edit endpoint).", 16),
               size=core.E(["auto", "1024x1024", "1536x1024", "1024x1536", "2048x2048", "3840x2160", "2160x3840"], "auto", "Output size."),
               quality=core.E(["auto", "low", "medium", "high"], "auto"), background=core.E(["auto", "transparent", "opaque"], "auto"),
               output_format=core.E(["png", "jpeg", "webp"], "png"), n=core.N(1, 10, 1, "How many images."))
VIDEO = core.S(prompt=core.T("What happens in the video."), input_reference=core.F("image", "Optional first frame."),
               seconds=core.E(["4", "8", "12"], "4"), size=core.E(["1280x720", "720x1280", "1792x1024", "1024x1792"], "1280x720"))


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    return [{"id": m["id"], "name": m["id"], "cat": "video" if "sora" in m["id"] else "image", "desc": "OpenAI"}
            for m in call(f"{API}/models").get("data", []) if m["id"].startswith(("gpt-image", "dall-e", "sora", "chatgpt-image"))]


def schema(mid):
    return VIDEO if "sora" in mid else IMAGE


def _images(r, fmt):
    return [core.bytes_uri(base64.b64decode(d["b64_json"]), "image/" + fmt) if d.get("b64_json") else d.get("url") for d in r.get("data", [])]


def run(mid, body, job):
    if "sora" not in mid:
        imgs = body.pop("images", None)
        if imgs:
            files = [("image[]", (f"in{i}.png", *core.uri_bytes(u)[:2])) for i, u in enumerate(imgs)]
            data, ctype = core.multipart({"model": mid, **{k: str(v) for k, v in body.items()}}, files)
            r = call(f"{API}/images/edits", data=data, ctype=ctype, timeout=900)
        else:
            r = call(f"{API}/images/generations", {"model": mid, **body}, timeout=900)
        return core.scrub(r), _images(r, body.get("output_format", "png"))
    ref = body.pop("input_reference", None)
    data, ctype = core.multipart({"model": mid, **{k: str(v) for k, v in body.items()}},
                                 [("input_reference", ("first.png",) + core.uri_bytes(ref)[:2])] if ref else [])
    d = call(f"{API}/videos", data=data, ctype=ctype)
    job["request_id"] = d.get("id")

    def check():
        r = call(f"{API}/videos/{d['id']}")
        if r.get("status") == "completed":
            payload, kind = call(f"{API}/videos/{d['id']}/content", raw=True, timeout=600)
            return r, [core.bytes_uri(payload, kind or "video/mp4")]
        if r.get("status") == "failed":
            raise RuntimeError(f"OpenAI: {(r.get('error') or {}).get('message') or 'the video failed'}")
    return core.wait(job, check, LABEL, every=5)


def test():
    return f"Connected · {len(models())} image/video models available"
