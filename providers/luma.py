"""Luma AI Dream Machine: Ray video and Photon images. Luma only accepts image links, not files from your PC."""
from . import _core as core

ID, LABEL, GROUP = "luma", "Luma AI", "maker"
KEYS = ["LUMAAI_API_KEY"]
LINK, BILLING = "https://lumalabs.ai/api/keys", "lumalabs.ai/api/billing"
HELP = "Luma Ray video and Photon images direct from Luma. Images must be links (e.g. an earlier result), not files from your PC."
API = "https://api.lumalabs.ai/dream-machine/v1"
call = core.caller(__name__)
VIDEO_MODELS, IMAGE_MODELS = ["ray-2", "ray-flash-2"], ["photon-1", "photon-flash-1"]
ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"]
VIDEO = core.S(prompt=core.T("What happens in the video."), start_image=core.F("image", "Optional first frame (a link)."),
               end_image=core.F("image", "Optional last frame (a link)."), aspect_ratio=core.E(ASPECTS, "16:9"),
               resolution=core.E(["540p", "720p", "1080p", "4k"], "720p"), duration=core.E(["5s", "9s"], "5s"), loop=core.B(False))
IMAGE = core.S(prompt=core.T("What to make."), aspect_ratio=core.E(ASPECTS, "16:9"), image_ref=core.F("image", "Images to borrow content from (links).", 4),
               style_ref=core.F("image", "Image whose style to copy (a link).", 1), character_ref=core.F("image", "Pictures of a person to keep (links).", 4),
               modify_image_ref=core.F("image", "Image to change (a link)."))


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    return ([{"id": m, "name": m, "cat": "video", "desc": "Luma Ray"} for m in VIDEO_MODELS]
            + [{"id": m, "name": m, "cat": "image", "desc": "Luma Photon"} for m in IMAGE_MODELS])


def schema(mid):
    return IMAGE if mid.startswith("photon") else VIDEO


def run(mid, body, job):
    if any(isinstance(v, str) and v.startswith("data:") or isinstance(v, list) and any(str(x).startswith("data:") for x in v) for v in body.values()):
        raise RuntimeError("Luma only takes image links. Use an earlier result (they're links) or an image's web address instead of a file from your PC.")
    if mid.startswith("photon"):
        payload = {"model": mid, "prompt": body.get("prompt", ""), "aspect_ratio": body.get("aspect_ratio", "16:9")}
        if body.get("image_ref"):
            payload["image_ref"] = [{"url": u, "weight": 0.85} for u in body["image_ref"]]
        if body.get("style_ref"):
            payload["style_ref"] = [{"url": u, "weight": 0.8} for u in body["style_ref"]]
        if body.get("character_ref"):
            payload["character_ref"] = {"identity0": {"images": body["character_ref"]}}
        if body.get("modify_image_ref"):
            payload["modify_image_ref"] = {"url": body["modify_image_ref"], "weight": 1.0}
        d = call(f"{API}/generations/image", payload)
    else:
        payload = {"model": mid, **{k: v for k, v in body.items() if k not in ("start_image", "end_image")}}
        frames = {f"frame{i}": {"type": "image", "url": body[k]} for i, k in enumerate(("start_image", "end_image")) if body.get(k)}
        if frames:
            payload["keyframes"] = frames
        d = call(f"{API}/generations", payload)
    job["request_id"] = d.get("id")

    def check():
        r = call(f"{API}/generations/{d['id']}")
        if r.get("state") == "completed":
            return r, core.media_urls(r.get("assets"), "assets")
        if r.get("state") == "failed":
            raise RuntimeError(f"Luma: {r.get('failure_reason') or 'the generation failed'}")
    return core.wait(job, check, LABEL, every=4)


def test():
    call(f"{API}/generations?limit=1")
    return "Connected to Luma"
