"""BytePlus ModelArk: ByteDance's Seedream (images) and Seedance (video) direct from ByteDance."""
from . import _core as core

ID, LABEL, GROUP = "byteplus", "BytePlus (Seedream, Seedance)", "maker"
KEYS = ["ARK_API_KEY"]
LINK, BILLING = "https://console.byteplus.com/ark/region:ark+ap-southeast-1/apiKey", "console.byteplus.com/ark (Billing)"
HELP = "Seedream images and Seedance video direct from ByteDance (BytePlus ModelArk, international)."
API = "https://ark.ap-southeast.bytepluses.com/api/v3"
call = core.caller(__name__)
IMAGE = core.S(prompt=core.T("What to make, or how to change the images."), image=core.F("image", "Images to edit or use as references.", 14),
               size=core.T("1K, 2K, 4K, or exact like 2048x2048.", "2K"), seed=core.N(-1, 2 ** 31),
               sequential_image_generation=core.E(["disabled", "auto"], "disabled", "auto lets it make a related set of images."),
               max_images=core.N(1, 15, None, "Most images in a set (with sequential generation)."), watermark=core.B(False))
VIDEO = core.S(prompt=core.T("What happens in the video."), first_frame=core.F("image", "Optional first frame."),
               last_frame=core.F("image", "Optional last frame."), reference_images=core.F("image", "Optional references (people, products, styles).", 9),
               resolution=core.E(["480p", "720p", "1080p"], "720p"), ratio=core.E(["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"], "adaptive"),
               duration=core.N(2, 15, 5, "Seconds."), generate_audio=core.B(None, "Add sound (models that support it)."), seed=core.N(-1, 2 ** 31),
               watermark=core.B(False))


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    return [{"id": m["id"], "name": m.get("name") or m["id"], "cat": "video" if "seedance" in m["id"] else "image", "desc": "ByteDance"}
            for m in call(f"{API}/models").get("data", []) if any(w in m["id"] for w in ("seedream", "seedance", "seededit"))]


def schema(mid):
    return VIDEO if "seedance" in mid else IMAGE


def run(mid, body, job):
    if "seedance" not in mid:
        n = body.pop("max_images", None)
        payload = {"model": mid, "response_format": "url", **body}
        if n:
            payload["sequential_image_generation_options"] = {"max_images": n}
        r = call(f"{API}/images/generations", payload, timeout=900)
        return r, core.media_urls(r.get("data"), "data")
    content = [{"type": "text", "text": body.pop("prompt", "")}]
    for role in ("first_frame", "last_frame"):
        if body.get(role):
            content.append({"type": "image_url", "image_url": {"url": body.pop(role)}, "role": role})
    content += [{"type": "image_url", "image_url": {"url": u}, "role": "reference_image"} for u in body.pop("reference_images", None) or []]
    d = call(f"{API}/contents/generations/tasks", {"model": mid, "content": content, **body})
    job["request_id"] = d.get("id")

    def check():
        r = call(f"{API}/contents/generations/tasks/{d['id']}")
        if r.get("status") == "succeeded":
            return r, [(r.get("content") or {}).get("video_url")]
        if r.get("status") in ("failed", "cancelled", "expired"):
            raise RuntimeError(f"BytePlus: {(r.get('error') or {}).get('message') or r.get('status')}")
    return core.wait(job, check, LABEL, cancel=lambda: call(f"{API}/contents/generations/tasks/{d['id']}", method="DELETE"), every=4)


def test():
    return f"Connected · {len(models())} Seedream/Seedance models"
