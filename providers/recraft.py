"""Recraft: design-friendly images and true vector (SVG) output, direct from Recraft."""
from . import _core as core

ID, LABEL, GROUP = "recraft", "Recraft", "maker"
KEYS = ["RECRAFT_API_TOKEN"]
LINK, BILLING = "https://app.recraft.ai/profile/api", "app.recraft.ai/profile/api"
HELP = "Recraft V4.1 images and editable SVG vectors (models ending in _vector), good for logos, icons and design work."
API = "https://external.api.recraft.ai/v1"
call = core.caller(__name__)
MODELS = ["recraftv4_1", "recraftv4_1_flash", "recraftv4_1_vector", "recraftv4_styles", "recraftv3", "recraftv3_vector"]
SIZES = ["1024x1024", "1365x1024", "1024x1365", "1536x1024", "1024x1536", "1820x1024", "1024x1820", "2048x2048"]
GEN = core.S(prompt=core.T("What to make."), style=core.T("Optional style, e.g. realistic_image, digital_illustration, vector_illustration, icon."),
             size=core.E(SIZES, None), n=core.N(1, 6, 1, "How many images."), negative_prompt=core.T("What to avoid (V3)."))
EDIT = core.S(("prompt", "image"), prompt=core.T("How to change the image."), image=core.F("image", "The image to change."),
              strength=core.N(0, 1, 0.5, "How much to change it (1 = a lot).", False), style=core.T("Optional style."), n=core.N(1, 6, 1))


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def models():
    return ([{"id": m, "name": m, "cat": "vector" if m.endswith("_vector") else "text-to-image", "desc": "Recraft"} for m in MODELS]
            + [{"id": "image-to-image", "name": "Recraft image to image", "cat": "image-to-image", "desc": "Change an existing image with a prompt."}])


def schema(mid):
    return EDIT if mid == "image-to-image" else GEN


def run(mid, body, job):
    if mid == "image-to-image":
        img = body.pop("image")
        data, ctype = core.multipart({k: str(v) for k, v in body.items()}, [("image", ("image.png", *core.uri_bytes(img)[:2]))])
        r = call(f"{API}/images/imageToImage", data=data, ctype=ctype, timeout=600)
    else:
        r = call(f"{API}/images/generations", {"model": mid, **body}, timeout=600)
    return r, [d["url"] for d in r.get("data", []) if d.get("url")]


def test():
    me = call(f"{API}/users/me")
    return f"Connected · {me.get('credits', '?')} API units"
