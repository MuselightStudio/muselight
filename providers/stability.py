"""Stability AI: Stable Image Ultra and Core, and Stable Diffusion 3.5, direct from Stability."""
from . import _core as core

ID, LABEL, GROUP = "stability", "Stability AI", "maker"
KEYS = ["STABILITY_API_KEY"]
LINK, BILLING = "https://platform.stability.ai/account/keys", "platform.stability.ai/account/credits"
HELP = "Stable Image Ultra and Core and Stable Diffusion 3.5 direct from Stability AI."
API = "https://api.stability.ai"
call = core.caller(__name__)
ASPECTS = ["1:1", "16:9", "21:9", "3:2", "5:4", "4:5", "2:3", "9:16", "9:21"]
STYLES = ["enhance", "anime", "photographic", "digital-art", "comic-book", "fantasy-art", "line-art", "analog-film", "neon-punk", "isometric",
          "low-poly", "origami", "modeling-compound", "cinematic", "3d-model", "pixel-art", "tile-texture"]
MODELS = {"ultra": "Stable Image Ultra", "core": "Stable Image Core", "sd3.5-large": "SD 3.5 Large", "sd3.5-large-turbo": "SD 3.5 Large Turbo",
          "sd3.5-medium": "SD 3.5 Medium"}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0]), "Accept": "image/*"}


def models():
    return [{"id": m, "name": n, "cat": "text-to-image", "desc": "Stability AI"} for m, n in MODELS.items()]


def schema(mid):
    props = dict(prompt=core.T("What to make."), negative_prompt=core.T("What to avoid."), aspect_ratio=core.E(ASPECTS, "1:1"),
                 seed=core.N(0, 4294967294), output_format=core.E(["png", "jpeg", "webp"], "png"))
    if mid != "ultra":
        props["style_preset"] = core.E(STYLES)
    if mid != "core":
        props.update(image=core.F("image", "Optional starting image."), strength=core.N(0, 1, None, "How much to change the starting image.", False))
    if mid.startswith("sd3"):
        props["cfg_scale"] = core.N(1, 10, None, "Prompt strength.", False)
    return core.S(**props)


def run(mid, body, job):
    img = body.pop("image", None)
    fields = {k: str(v) for k, v in body.items()}
    path = "/v2beta/stable-image/generate/" + ("sd3" if mid.startswith("sd3") else mid)
    if mid.startswith("sd3"):
        fields.update(model=mid, mode="image-to-image" if img else "text-to-image")
    data, ctype = core.multipart(fields, [("image", ("start.png", *core.uri_bytes(img)[:2]))] if img else [])
    r = call(API + path, data=data, ctype=ctype, timeout=600)
    if not isinstance(r, tuple):
        raise RuntimeError(f"Stability AI: {r}")
    return {"model": mid}, [core.bytes_uri(*r)]


def test():
    return f"Connected · {call(f'{API}/v1/user/balance', headers={'Accept': 'application/json'}).get('credits', 0):.1f} credits"
