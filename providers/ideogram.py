"""Ideogram: images with the best text rendering, direct from Ideogram."""
from . import _core as core

ID, LABEL, GROUP = "ideogram", "Ideogram", "maker"
KEYS = ["IDEOGRAM_API_KEY"]
LINK, BILLING = "https://ideogram.ai/manage-api", "ideogram.ai/manage-api"
HELP = "Ideogram 4.5, 4.0 and 3.0 images, known for clean text and logos."
API = "https://api.ideogram.ai/v2/image/generate"
call = core.caller(__name__)
SPEED = core.E(["FLASH", "TURBO", "DEFAULT", "QUALITY"], None, "Faster is cheaper.")
SCHEMAS = {
    "ideogram-4-5": core.S(prompt=core.T("What to make, or how to change the images."), images=core.F("image", "Images to edit (first) and references.", 5),
                           size=core.T("auto, source, or WIDTHxHEIGHT like 1024x1024.", "auto"), background=core.E(["auto", "transparent", "opaque"], "auto"),
                           quality=core.E(["very_low", "low", "medium", "high"], None), magic_prompt=core.E(["auto", "on", "off"], "auto"),
                           num_images=core.N(1, 8, 1), seed=core.N(0, 2147483647)),
    "ideogram-4": core.S(prompt=core.T("What to make."), resolution=core.T("e.g. 1024x1024 (empty = automatic)."), rendering_speed=SPEED,
                         magic_prompt=core.E(["auto", "on", "off"], "auto"), num_images=core.N(1, 8, 1), seed=core.N(0, 2147483647)),
    "ideogram-3": core.S(prompt=core.T("What to make."), negative_prompt=core.T("What to avoid."),
                         aspect_ratio=core.E(["1x1", "16x9", "9x16", "4x3", "3x4", "3x2", "2x3", "16x10", "10x16", "3x1", "1x3"], None), rendering_speed=SPEED,
                         style_type=core.E(["AUTO", "GENERAL", "REALISTIC", "DESIGN", "FICTION"], None), style_reference_images=core.F("image", "Style examples.", 3),
                         magic_prompt=core.E(["AUTO", "ON", "OFF"], None), num_images=core.N(1, 8, 1), seed=core.N(0, 2147483647)),
}


def headers():
    return {"Api-Key": core.key(KEYS[0])}


def models():
    return [{"id": m, "name": m.replace("-", " ").title().replace("4 5", "4.5"), "cat": "text-to-image", "desc": "Ideogram"} for m in SCHEMAS]


def schema(mid):
    if mid not in SCHEMAS:
        raise RuntimeError(f"Ideogram has no model called '{mid}' in this app.")
    return SCHEMAS[mid]


def quote(mid, body):
    """Ideogram prices the request without running it (dry_run)."""
    files = [(k, (f"img{i}.png", *core.uri_bytes(u)[:2])) for k in ("images", "style_reference_images") for i, u in enumerate(body.get(k) or [])]
    rest = {k: v for k, v in body.items() if k not in ("images", "style_reference_images")}
    if mid == "ideogram-4":
        r = call(f"{API}/{mid}?dry_run=true", rest, timeout=60)
    else:
        data, ctype = core.multipart({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in rest.items()}, files)
        r = call(f"{API}/{mid}?dry_run=true", data=data, ctype=ctype, timeout=60)
    return core.amount(r)


def run(mid, body, job):
    files = [(k, (f"img{i}.png", *core.uri_bytes(u)[:2])) for k in ("images", "style_reference_images") for i, u in enumerate(body.pop(k, None) or [])]
    if mid == "ideogram-4":
        r = call(f"{API}/{mid}", body, timeout=600)
    else:
        data, ctype = core.multipart({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in body.items()}, files)
        r = call(f"{API}/{mid}", data=data, ctype=ctype, timeout=600)
    imgs = r.get("data") or []
    if imgs and not any(i.get("url") for i in imgs):
        raise RuntimeError("Ideogram's safety check held back the images.")
    return r, [i["url"] for i in imgs if i.get("url")]


def test():
    try:
        call(f"{API}/ideogram-4?dry_run=true", {"prompt": "test"})
    except RuntimeError as e:
        if "didn't accept your key" in str(e):
            raise
    return "Connected to Ideogram"
