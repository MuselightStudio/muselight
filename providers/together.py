"""Together AI: FLUX, Imagen, Gemini image and several video models. Settings are the common ones its docs list;
a model ignores the ones it doesn't use."""
from . import _core as core

ID, LABEL, GROUP = "together", "Together AI", "market"
KEYS = ["TOGETHER_API_KEY"]
LINK, BILLING = "https://api.together.ai/settings/api-keys", "api.together.ai/settings/billing"
HELP = "FLUX (including FLUX.2), Kontext editing, Google image models and video models; also a cheap option for the assistant."
API = "https://api.together.xyz"
call = core.caller(__name__)
kinds = {}

IMAGE = core.S(prompt=core.T("What to make."), negative_prompt=core.T("What to avoid (some models)."),
               width=core.N(64, 2048, None, "Width (FLUX.1, FLUX.2)."), height=core.N(64, 2048, None, "Height (FLUX.1, FLUX.2)."),
               aspect_ratio=core.E(["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"], None, "Shape (Kontext, Schnell)."),
               steps=core.N(1, 50, None, "Steps (some models)."), guidance_scale=core.N(0, 20, None, "Prompt strength (FLUX.2 dev/flex).", False),
               n=core.N(1, 4, None, "How many images."), seed=core.N(0, 2 ** 32), image_url=core.F("image", "Image to edit (Kontext, FLUX.2, Google)."),
               reference_images=core.F("image", "Reference images (FLUX.2, Google).", 8), output_format=core.E(["jpeg", "png"]),
               disable_safety_checker=core.B(None, "Turn off the safety filter."))
VIDEO = core.S(prompt=core.T("What happens in the video."), negative_prompt=core.T("What to avoid."), width=core.N(256, 1920), height=core.N(256, 1920),
               seconds=core.E(["5", "6", "8", "10"], None, "Length in seconds."), resolution=core.E(["720P", "1080P"], None, "Wan 2.7 models."),
               ratio=core.E(["16:9", "9:16", "1:1", "4:3", "3:4"], None, "Wan 2.7 models."), fps=core.N(15, 60), steps=core.N(10, 50),
               guidance_scale=core.N(1, 20, None, "", False), seed=core.N(0, 2 ** 32), first_frame=core.F("image", "Optional first frame."),
               last_frame=core.F("image", "Optional last frame."), reference_images=core.F("image", "Characters or objects to keep.", 4))


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    out = []
    for m in call(f"{API}/v1/models"):
        if m.get("type") in ("image", "video"):
            kinds[m["id"]] = m["type"]
            out.append({"id": m["id"], "name": m.get("display_name") or m["id"], "cat": m["type"], "desc": m.get("organization") or "",
                        "price": core.price((m.get("pricing") or {}).get("base")) if (m.get("pricing") or {}).get("base") else ""})
    return out


def schema(mid):
    if mid not in kinds:
        models()
    return VIDEO if kinds.get(mid) == "video" else IMAGE


def run(mid, body, job):
    if schema(mid) is IMAGE:
        r = call(f"{API}/v1/images/generations", {"model": mid, "response_format": "url", **body}, timeout=600)
        return r, core.media_urls(r.get("data"), "data")
    media = {}
    frames = [{"input_image": body.pop(k), "frame": k.split("_")[0]} for k in ("first_frame", "last_frame") if body.get(k)]
    if frames:
        media["frame_images"] = frames
    if body.get("reference_images"):
        media["reference_images"] = body.pop("reference_images")
    d = call(f"{API}/v2/videos", {"model": mid, **body, **({"media": media} if media else {})})
    job["request_id"] = d.get("id")

    def check():
        r = call(f"{API}/v2/videos/{d['id']}")
        if r.get("status") == "completed":
            return r, core.media_urls(r.get("outputs"), "outputs")
        if r.get("status") in ("failed", "cancelled"):
            raise RuntimeError(f"Together: {(r.get('error') or {}).get('message') or r.get('status')}")
    return core.wait(job, check, LABEL, every=4)


def test():
    n = len([m for m in call(f"{API}/v1/models") if m.get("type") in ("image", "video")])
    return f"Connected · {n} image and video models"
