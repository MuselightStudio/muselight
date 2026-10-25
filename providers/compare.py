"""Price comparison: find the same model on every provider, estimate what this run would cost on each, and pick the cheapest
provider you're connected to, translating the settings into that provider's names.

Matching is deliberately strict: two ids are "the same model" only when their family, version, tier (pro, fast, turbo…) and mode
(text-to-video, image-to-video, edit…) all agree. A missed match just means no switch; a wrong match would run a different model.
Prices are list prices from each provider's catalogue, so savings are estimates.
"""
import functools, math, re

from . import _core as core

# providers whose prices can be read without an account, so the app can say "this one would be cheaper"
PUBLIC_PRICES = ("muselight", "wavespeed", "atlas", "runware", "segmind", "deepinfra", "runpod")

ORG = {"fal", "ai", "falai", "wavespeed", "black", "forest", "labs", "bfl", "bytedance", "google", "openai", "kwaivgi", "kuaishou", "alibaba",
       "stabilityai", "runware", "prunaai", "community", "official", "replicate", "segmind", "deepinfra", "atlascloud", "tongyi", "mai",
       "minimax", "xai", "lumalabs", "runwayml", "klingai", "ideogramai", "recraftai", "luma"}
FILLER = {"v", "video", "videos", "image", "images", "model", "models", "generation", "generate", "api", "preview", "latest", "to", "the", "and",
          "for", "with", "s", "beta", "new", "ready", "made", "your", "gpu", "endpoint",
          "us", "eu", "global", "intl"}  # where it's hosted, not which model
PHRASES = [(r"text[-_ ]?to[-_ ]?video|text2video|txt2vid|\bt2v\b", " ttv "), (r"image[-_ ]?to[-_ ]?video|image2video|img2vid|\bi2v\b", " itv "),
           (r"reference[-_ ]?to[-_ ]?video|ref2v|\br2v\b", " rtv "), (r"video[-_ ]?to[-_ ]?video|\bv2v\b", " vtv "), (r"start[-_ ]?end[-_ ]?frame|first[-_ ]?last[-_ ]?frame|fl2v", " flf "),
           (r"image[-_ ]?to[-_ ]?image|img2img|i2i|image[-_ ]?edit(ing)?|edit(ing)?", " edit "), (r"text[-_ ]?to[-_ ]?image|txt2img|t2i", " "),
           (r"\bstd\b", " standard "), (r"\bmaster\b", " master ")]
MODES = {"ttv", "itv", "rtv", "vtv", "flf", "edit"}  # text/image/reference/video to video, first+last frame, edit


@functools.lru_cache(maxsize=None)  # thousands of ids, checked on every model-list and price request
def canon(mid, cat=""):
    """The identity of a model, the same across providers: e.g. 'fal-ai/kling-video/v2.1/pro/image-to-video' and
    'kwaivgi/kling-v2.1-i2v-pro' both give '2.1 itv kling pro'."""
    s = mid.lower()
    for pat, rep in PHRASES:
        s = re.sub(pat, rep, s)
    raw = [t for t in re.split(r"[^a-z0-9.]+", s) if t]
    tokens = []
    for t in raw:  # split letters from digits: veo3 -> veo 3, v2.1 -> v 2.1, a14b -> a 14 b
        tokens += [x for x in re.findall(r"\d+(?:\.\d+)*|[a-z]+", t)]
    merged = []
    for t in tokens:  # 4-5 -> 4.5, 2-1 -> 2.1 (one level only)
        if merged and t.isdigit() and merged[-1].isdigit() and len(t) <= 2 and len(merged[-1]) <= 2:
            merged[-1] = f"{merged[-1]}.{t}"
        else:
            merged.append(t)
    out = set()
    for t in merged:
        if re.fullmatch(r"\d+(\.\d+)*", t):
            if len(t.replace(".", "")) >= 6:
                continue  # build dates (seedream-4-0-250828)
            t = re.sub(r"\.0+$", "", t.lstrip("0") or "0") or "0"
        elif re.fullmatch(r"\d+p|[1248]k|\d+x\d+", t) or t in ORG or t in FILLER:
            continue  # resolutions are settings, not models; makers' names vary by provider
        out.add(t)
    if [t for t in out if t[0].isdigit()] == ["1"]:
        out.discard("1")  # FLUX.1 schnell = FLUX schnell
    c = cat.lower()
    if not [t for t in out if t.isalpha() and t not in MODES]:
        return None  # only numbers and a mode left: too vague to match safely
    # images and videos never match each other (an image edit isn't a video edit)
    video = out & {"ttv", "itv", "rtv", "vtv", "flf"} or re.search(r"video|vid|clip", mid.lower() + " " + c)
    audio = re.search(r"audio|speech|music|voice|sound|tts", mid.lower() + " " + c) and not video
    out.add("~video" if video else "~audio" if audio else "~image")
    if not out & MODES:
        for key, mode in (("image-to-video", "itv"), ("text-to-video", "ttv"), ("reference-to-video", "rtv"), ("video-to-video", "vtv"),
                          ("image-to-image", "edit"), ("edit", "edit")):
            if re.search(r"(?<![a-z])" + key, c):  # at a word start: "Muselight Credits" isn't an edit model
                out.add(mode)
                break
    return " ".join(sorted(out))


# ---------- what a run costs ----------
FAL_SIZES = {"square_hd": (1024, 1024), "square": (512, 512), "portrait_4_3": (768, 1024), "portrait_16_9": (576, 1024),
             "landscape_4_3": (1024, 768), "landscape_16_9": (1024, 576)}


def _key(name):
    return name.lower().replace("_", "").replace("-", "")


ROLES = {
    "prompt": {"prompt", "positiveprompt", "prompttext", "text"},
    "negative": {"negativeprompt"},
    "seed": {"seed", "noiseseed"},
    "count": {"numimages", "n", "numberresults", "batchsize", "numoutputs", "numberofimages", "maximages", "samples", "numsamples"},
    "steps": {"numinferencesteps", "steps", "numsteps"},
    "guidance": {"guidancescale", "guidance", "cfg", "cfgscale"},
    "duration": {"duration", "seconds", "durationseconds", "videolength"},
    "aspect": {"aspectratio", "ratio", "aspect"},
    "resolution": {"resolution"},
    "size": {"imagesize", "size"},
    "width": {"width"}, "height": {"height"},
}
ROLE_OF = {k: r for r, keys in ROLES.items() for k in keys}


def _num(v):
    m = re.search(r"\d+(\.\d+)?", str(v)) if v is not None else None
    return float(m.group()) if m else None


def _dims(v):
    """(width, height) from a size value: fal's names, {width, height}, '1280*720', '1024x1024', '16:9'."""
    if isinstance(v, dict) and v.get("width"):
        return v["width"], v.get("height") or v["width"]
    if isinstance(v, str):
        if v in FAL_SIZES:
            return FAL_SIZES[v]
        m = re.fullmatch(r"(\d+)\s*[x*×:]\s*(\d+)", v.strip())
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            return (w, h) if w > 32 else (1024 * w / max(w, h), 1024 * h / max(w, h))  # an aspect ratio
    return None


def roles(body):
    """The settings that matter for price and translation, by meaning rather than by each provider's name."""
    out = {}
    for k, v in body.items():
        r = ROLE_OF.get(_key(k))
        if r and v not in (None, "", []):
            out.setdefault(r, v)
    return out


def estimate(cost, body, schema=None):
    """Estimated price of this run, from a list price and the run's settings (defaults from the schema)."""
    if not cost:
        return None
    r = {**roles({k: p.get("default") for k, p in ((schema or {}).get("properties") or {}).items() if "default" in p}), **roles(body)}
    n = max(1, int(_num(r.get("count")) or 1))
    if cost["per"] == "image":
        return cost["usd"] * n
    if cost["per"] == "second":
        return cost["usd"] * (_num(r.get("duration")) or 5)
    if cost["per"] == "clip":  # a price for the default length: longer videos cost proportionally more
        return cost["usd"] * (_num(r.get("duration")) or 5) / 5 * n
    if cost["per"] == "kchar":
        return cost["usd"] * max(1, len(str(r.get("prompt") or ""))) / 1000
    if cost["per"] == "megapixel":
        wh = (r.get("width"), r.get("height")) if r.get("width") else _dims(r.get("size")) or _dims(r.get("aspect")) or (1024, 1024)
        return cost["usd"] * max(0.25, (_num(wh[0]) or 1024) * (_num(wh[1]) or 1024) / 1e6) * n
    return cost["usd"] * n  # list prices are per output, so asking for several costs more


# ---------- translating settings between providers ----------
SOFT = re.compile(r"safety|nsfw|moderation|format|sync|base64|watermark|acceleration|optimi|expansion|extend|upsampl|enhance|magic|webhook", re.I)


def _files(schema):
    """File fields of a schema: name -> (kind, many, role) with role first / last / ref."""
    out = {}
    for k, p in (schema.get("properties") or {}).items():
        many = p.get("type") == "array"
        target = p.get("items") if many and isinstance(p.get("items"), dict) else p
        kind = target.get("_fal_ui_field") or core.file_kind(k, target)
        if kind not in ("image", "video", "audio") or target.get("type", "string") != "string":
            continue
        n = core.snake(k)
        role = "last" if re.search(r"last|end|tail", n) else "ref" if many or re.search(r"ref|style|subject|character", n) else "first"
        out[k] = (kind, many, role, p.get("maxItems"))
    return out


def _fit(v, p):
    """A value in the shape a field accepts: allowed values, number or text."""
    enum = [e for e in (p.get("enum") or []) if e is not None]
    types = {p.get("type")} | {o.get("type") for o in p.get("anyOf") or []}
    if enum:
        if v in enum:
            return v
        low = {str(e).lower().rstrip("s"): e for e in enum}
        if str(v).lower().rstrip("s") in low:
            return low[str(v).lower().rstrip("s")]
        nv, nums = _num(v), [(e, _num(e)) for e in enum if _num(e) is not None and not re.search(r"[:x*×]", str(e))]
        if nv is not None and nums and not re.search(r"[:x*×]", str(v)):
            return min(nums, key=lambda en: abs(en[1] - nv))[0]  # nearest allowed number (duration 6 -> 5)
        return None
    if "integer" in types and _num(v) is not None:
        return int(_num(v))
    if "number" in types and _num(v) is not None:
        return _num(v)
    if "string" in types and isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return v


def _ratio(wh):
    return wh[0] / wh[1] if wh and wh[1] else None


def _shape(src, dst_props, out):
    """Carry the picture's shape over: aspect ratio, a named size, or width and height."""
    wh = None
    if src.get("width") and src.get("height"):
        wh = (_num(src["width"]), _num(src["height"]))
    wh = wh or _dims(src.get("size")) or _dims(src.get("aspect"))
    if not wh:
        return True
    target = _ratio(wh)
    for k, p in dst_props.items():
        r = ROLE_OF.get(_key(k))
        if r in ("aspect", "size") and p.get("enum"):
            options = [(e, _ratio(_dims(str(e)))) for e in p["enum"]]
            options = [(e, r2) for e, r2 in options if r2]
            if options:
                out[k] = min(options, key=lambda o: abs(math.log(o[1] / target)))[0]
                return True
        if r == "size" and not p.get("enum") and p.get("type") == "string":
            out[k] = f"{int(wh[0])}x{int(wh[1])}" if "x" in str(p.get("default", "x")) else f"{int(wh[0])}*{int(wh[1])}"
            return True
        if r == "aspect" and not p.get("enum") and p.get("type") == "string":
            g = math.gcd(int(wh[0]), int(wh[1])) or 1
            out[k] = f"{int(wh[0]) // g}:{int(wh[1]) // g}"
            return True
    if "width" in dst_props and "height" in dst_props:
        out["width"], out["height"] = _fit(int(wh[0]), dst_props["width"]), _fit(int(wh[1]), dst_props["height"])
        return True
    return False


def translate(body, src_schema, dst_schema):
    """These settings in another provider's names. Returns (settings, None) or (None, why it can't be done faithfully)."""
    sp, dp = src_schema.get("properties") or {}, dst_schema.get("properties") or {}
    defaults = {k: p.get("default") for k, p in sp.items()}
    deliberate = {k for k, v in body.items() if v not in (None, "", []) and v != defaults.get(k) and not SOFT.search(k)}
    out, used = {}, set()
    # files: first frame, last frame and references keep their roles
    sf, df = _files(src_schema), _files(dst_schema)
    for kind in ("image", "video", "audio"):
        got = {"first": [], "last": [], "ref": []}
        for k, (kd, many, role, _) in sf.items():
            if kd == kind and body.get(k):
                vals = body[k] if isinstance(body[k], list) else [body[k]]
                got[role] += vals
                used.add(k)
        if not any(got.values()):
            continue
        slots = [(k, many, role, mx) for k, (kd, many, role, mx) in df.items() if kd == kind]
        if not slots:
            return None, f"it has no {kind} input"
        left = got["first"] + got["ref"]
        for k, many, role, mx in sorted(slots, key=lambda s: ("first", "last", "ref").index(s[2])):
            if role == "last" and got["last"]:
                out[k] = got["last"] if many else got["last"][0]
            elif role != "last" and left:
                take = left[: (mx or 99)] if many else left[:1]
                out[k] = take if many else take[0]
                left = left[len(take):]
        if got["last"] and not any(role == "last" for _, _, role, _ in slots):
            return None, "it has no last-frame input"
        if left and any(v in left for v in got["first"]):
            return None, f"it takes fewer {kind}s"
    # meaning-based settings: prompt, seed, count, duration, steps…
    src_roles = {}
    for k, v in body.items():
        r = ROLE_OF.get(_key(k))
        if r and k not in used:
            src_roles.setdefault(r, v)
            used.add(k)
    if not _shape(src_roles, dp, out) and any(k in deliberate for k in body if ROLE_OF.get(_key(k)) in ("aspect", "size", "width", "height")):
        return None, "it can't set the picture shape"
    for k, p in dp.items():
        r = ROLE_OF.get(_key(k))
        if r and r in src_roles and r not in ("aspect", "size", "width", "height") and k not in out:
            v = _fit(src_roles[r], p)
            if v is not None:
                out[k] = v
    for r in src_roles:
        if r not in ("aspect", "size", "width", "height") and not any(ROLE_OF.get(_key(k)) == r for k in out):
            src_keys = [k for k in body if ROLE_OF.get(_key(k)) == r]
            if any(k in deliberate for k in src_keys) and not (r == "count" and int(_num(src_roles[r]) or 1) == 1):
                return None, f"it has no {r} setting"
    # anything else with the same name
    for k, v in body.items():
        if k in used or v in (None, "", []):
            continue
        if k in dp:
            fv = _fit(v, dp[k])
            if fv is not None:
                out[k] = fv
                continue
        if k in deliberate:
            return None, f"it has no '{k}' setting"
    # a required setting that's simply not filled in yet (the prompt before it's typed) is the user's to fill, not a mismatch
    src_roles_all = {ROLE_OF.get(_key(k)) for k in sp} | {("file", kd) for kd, *_ in sf.values()}
    missing = [k for k in dst_schema.get("required") or [] if k not in out and "default" not in dp.get(k, {})
               and ROLE_OF.get(_key(k)) not in src_roles_all and ("file", (df.get(k) or ("",))[0]) not in src_roles_all]
    if missing:
        return None, "it needs " + ", ".join(missing)
    return out, None


# ---------- choosing ----------

def options(model, body, index, item_of, schema_of, cost_of, connected):
    """Every provider that has this model: [{model, provider, connected, est, why_not}], cheapest first.
    index: canon key -> model ids; item_of(id) -> catalogue item; schema_of(id) -> schema; cost_of(id) -> cost or None."""
    me = item_of(model)
    key = canon(_bare(model), (me or {}).get("cat", "")) if me else None
    members = index.get(key, []) if key else []
    if model not in members:
        members = [model] + members
    try:
        src_schema = schema_of(model)
    except Exception:
        src_schema = {}  # e.g. a provider that only shows settings to connected accounts
    rows = []
    for mid in members:
        prov = "fal" if _bare(mid) == mid else mid.split(":", 1)[0]
        try:
            cost = cost_of(mid)
            est = estimate(cost, body, src_schema)
        except Exception:
            cost, est = None, None
        rows.append({"model": mid, "provider": prov, "connected": connected(prov), "est": est, "cost": cost, "name": (item_of(mid) or {}).get("name", mid)})
    # one yardstick for every provider: price per second of video, or per image, for these settings
    video = bool(key and "~video" in key.split()) or "video" in (me or {}).get("cat", "")
    r_ = {**roles({k: p.get("default") for k, p in (src_schema.get("properties") or {}).items() if "default" in p}), **roles(body)}
    units = (_num(r_.get("duration")) or 5) if video else max(1, int(_num(r_.get("count")) or 1))
    for r in rows:
        r["metric"], r["units"] = ("second" if video else "image"), units
        r["per_unit"] = r["est"] / units if r["est"] is not None else None
    rows.sort(key=lambda r: (r["est"] is None, r["est"] or 0))
    return rows, src_schema


def _bare(model):
    p, sep, rest = model.partition(":")
    from . import MODULES
    return rest if sep and p in MODULES else model


def choose(model, body, rows, src_schema, schema_of):
    """The cheapest connected provider whose settings fit, if it's cheaper than the one asked for: (model, settings, row) or None."""
    asked = next((r for r in rows if r["model"] == model), None)
    if asked and not asked["connected"]:
        # a provider you haven't connected: run the same model where you are connected, cheapest first
        for r in rows:
            if r["connected"]:
                try:
                    out, why = translate(body, src_schema, schema_of(r["model"]))
                except Exception as e:
                    out, why = None, str(e)[:120]
                r["why_not"] = why
                if out is not None:
                    return r["model"], out, r
        return None
    if not asked or asked["est"] is None:
        return None  # can't tell whether anything is cheaper
    for r in rows:
        if r["model"] == model or not r["connected"] or r["est"] is None:
            continue
        if r["est"] >= asked["est"] * 0.99:
            break  # sorted: nothing further is cheaper
        try:
            out, why = translate(body, src_schema, schema_of(r["model"]))
        except Exception as e:
            out, why = None, str(e)[:120]
        r["why_not"] = why
        if out is not None:
            return r["model"], out, r
    return None


def selftest():
    assert canon("fal-ai/kling-video/v2.1/pro/image-to-video") == canon("kwaivgi/kling-v2.1-i2v-pro") == "2.1 itv kling pro ~video"
    assert canon("fal-ai/flux/schnell", "text-to-image") == canon("bfl-flux-1-schnell") == canon("black-forest-labs/FLUX.1-schnell") == "flux schnell ~image"
    assert canon("fal-ai/flux/schnell", "Muselight Credits · text-to-image") == "flux schnell ~image"  # "Credits" isn't "edit"
    assert "edit" in canon("fal-ai/flux-pro/kontext", "image editing")
    assert canon("fal-ai/flux-pro/v1.1-ultra") == canon("black-forest-labs/flux-1.1-pro-ultra") != canon("fal-ai/flux-pro/v1.1")
    assert canon("fal-ai/bytedance/seedream/v4.5/edit") == canon("seedream/4.5-edit") == canon("bytedance/seedream-v4.5/edit")
    assert canon("fal-ai/flux/dev") != canon("fal-ai/flux/dev/image-to-image") and canon("fal-ai/veo3") != canon("fal-ai/veo3.1")
    assert canon("seedream-4-0-250828") == canon("seedream-v4") and canon("minimax/hailuo-02-std", "image-to-video") == canon("fal-ai/minimax/hailuo-02/standard/image-to-video")
    assert canon("p-image-edit") != canon("p-video-edit") and canon("fal-ai/pixverse/v6/image-to-video") != canon("fal-ai/kling/v6/image-to-video")
    assert canon("bytedance/seedance-2.5/us/image-to-video", "image-to-video") == canon("bytedance/seedance-2.5/image-to-video")
    assert canon("seedream/v6/i2v") is not None and canon("fal-ai/v6/image-to-video") is None
    assert estimate({"usd": 0.1, "per": "kchar"}, {"text": "x" * 500}) == 0.05
    assert estimate({"usd": 0.5, "per": "clip"}, {"duration": 10}) == 1.0 and estimate({"usd": 0.1, "per": "run"}, {"n": 3}) == 0.30000000000000004
    assert translate({"prompt": "x", "num_images": 3}, {"properties": {"prompt": {}, "num_images": {"default": 1}}}, {"properties": {"prompt": {}}})[0] is None
    assert estimate({"usd": 0.1, "per": "second"}, {"duration": "8"}) == 0.8 and estimate({"usd": 0.02, "per": "image"}, {"num_images": 3}) == 0.06
    assert abs(estimate({"usd": 0.02, "per": "megapixel"}, {"image_size": "landscape_16_9"}) - 0.02 * 1024 * 576 / 1e6) < 1e-9
    fal = {"properties": {"prompt": {"type": "string"}, "image_size": {"enum": list(FAL_SIZES), "default": "landscape_4_3"},
                          "num_images": {"type": "integer", "default": 1}, "enable_safety_checker": {"type": "boolean", "default": True},
                          "image_url": {"type": "string"}}}
    other = {"properties": {"positivePrompt": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"},
                            "numberResults": {"type": "integer"}, "referenceImages": {"type": "array", "items": {"type": "string", "_fal_ui_field": "image"}}},
             "required": ["positivePrompt"]}
    out, why = translate({"prompt": "a cat", "image_size": "landscape_16_9", "num_images": 2, "enable_safety_checker": False, "image_url": "u"}, fal, other)
    assert why is None and out == {"positivePrompt": "a cat", "width": 1024, "height": 576, "numberResults": 2, "referenceImages": ["u"]}, out
    out, why = translate({"prompt": "a cat", "lora_scale": 0.8}, {"properties": {"prompt": {}, "lora_scale": {"default": 1}}}, other)
    assert out is None and "lora_scale" in why
    out, _ = translate({"prompt": "x", "duration": 6, "aspect_ratio": "9:16"}, {"properties": {"prompt": {}, "duration": {}, "aspect_ratio": {}}},
                       {"properties": {"prompt": {"type": "string"}, "duration": {"enum": ["5", "10"]}, "ratio": {"enum": ["1280:720", "720:1280"]}}})
    assert out == {"prompt": "x", "duration": "5", "ratio": "720:1280"}, out
    print("compare selftest ok")
