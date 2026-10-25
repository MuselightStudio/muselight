"""Plumbing shared by every provider module: HTTP with readable errors, waiting for results, and turning each
provider's settings description into the plain JSON schema the app's forms understand."""
import base64, json, mimetypes, os, re, sys, time, urllib.error, urllib.parse, urllib.request, uuid
from pathlib import Path

UA = "Muselight/1.0"  # some providers' firewalls turn away Python's default user agent
DATA = Path(".")  # studio_data, set by providers.init()


def key(name):
    return os.environ.get(name, "").strip()


def _message(x):
    """The human part of an error reply, however the provider nests it."""
    if isinstance(x, list):
        return "; ".join(f"{'.'.join(str(v) for v in e.get('loc', [])[1:]) or 'input'}: {e.get('msg', '')}" if isinstance(e, dict) and "loc" in e
                         else _message(e) for e in x)
    if isinstance(x, dict):
        for k in ("detail", "message", "msg", "error", "errors", "title", "status_msg"):
            if x.get(k):
                return _message(x[k])
        return json.dumps(x)
    return "" if x in (None, "null") else str(x)


def api_error(label, billing, code, text):
    """Turn a provider's error reply into one readable sentence."""
    try:
        detail = _message(json.loads(text))
    except ValueError:
        detail = text
    detail = re.sub(r"<[^>]+>", " ", detail or "").strip()[:600]
    low, tail = detail.lower(), f" ({detail})" if detail else ""
    if re.search(r"api.?key|token|unauthori[sz]ed|authenticat", low) and re.search(r"invalid|not valid|format|missing|expired|incorrect|unauthori", low):
        code = 401  # some providers report a bad key as a 400 or 422
    if code in (401, 403):
        return f"{label} didn't accept your key. Check it in Connections.{tail}"
    if code == 402 or "insufficient" in low or "balance" in low or ("credit" in low and "credits" not in label.lower()):
        return f"Your {label} account is out of credit. Add some at {billing}.{tail}"
    if code == 404:
        return f"{label} couldn't find that model or request.{tail}"
    if code in (400, 422):
        return f"{label} didn't accept these settings: {detail}"
    if code == 429:
        return f"{label} is limiting how fast you can run. Lower “At once” or try again shortly.{tail}"
    return f"{label} error {code}: {detail}"


class Busy(RuntimeError):
    """A server error or rate limit: worth asking again shortly."""


def http(mod, url, body=None, method=None, data=None, ctype="application/json", headers=None, timeout=120, raw=False, auth=True):
    """Call a provider. JSON replies come back parsed; anything else (an image, a video) comes back as (bytes, content type)."""
    h = {"User-Agent": UA, "Accept": "application/json, */*"}
    if auth:
        h.update(mod.headers())
    if body is not None:
        data = json.dumps(body).encode()
    if data is not None:
        h["Content-Type"] = ctype
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload, kind = r.read(), r.headers.get_content_type()
    except urllib.error.HTTPError as e:
        err = Busy if e.code >= 500 or e.code == 429 else RuntimeError
        raise err(api_error(mod.LABEL, getattr(mod, "BILLING", "your account page"), e.code, e.read().decode(errors="replace")))
    if raw or (kind and not kind.endswith("json") and not kind.startswith("text/")):
        return payload, kind
    if not payload.strip():
        return {}
    try:
        out = json.loads(payload)
    except ValueError:
        return payload.decode(errors="replace")
    if isinstance(out, dict) and str(out.get("code")) in ("400", "401", "402", "403", "404", "422", "429"):  # an error sent as HTTP 200 (Kie.ai…)
        raise RuntimeError(api_error(mod.LABEL, getattr(mod, "BILLING", "your account page"), int(out["code"]), payload.decode(errors="replace")))
    return out


def caller(name):
    """call(url, body=None, **kw) bound to one provider module (looked up when called, so modules can define it at the top)."""
    return lambda url, body=None, **kw: http(sys.modules[name], url, body, **kw)


def unwrap(d):
    """Replies shaped {code, data}: a non-success code is an error even on HTTP 200."""
    if isinstance(d, dict) and "data" in d and "code" in d:
        if str(d.get("code")) not in ("0", "200"):
            raise RuntimeError(str(d.get("message") or d.get("msg") or d))
        return d["data"]
    return d


def wait(job, check, label, cancel=None, every=2.5):
    """Poll check() until it returns something; stops early (returning None) when the run is cancelled."""
    misses = 0
    while True:
        if job["status"] == "cancelled":
            if cancel:
                try:
                    cancel()
                except Exception:
                    pass  # already finished on the provider's side
            return None
        try:
            r = check()
            misses = 0
        except (urllib.error.URLError, TimeoutError, OSError, Busy) as e:
            misses += 1
            if misses > 10:
                raise RuntimeError(f"Lost connection to {label} while waiting for the result ({str(e)[:120]})")
            time.sleep(3)
            continue
        if r is not None:
            return r
        time.sleep(every)


# ---------- files ----------

def datauri(path):
    path = Path(path)
    return f"data:{mimetypes.guess_type(path.name)[0] or 'application/octet-stream'};base64," + base64.b64encode(path.read_bytes()).decode()


def bytes_uri(payload, mime):
    return f"data:{mime or 'application/octet-stream'};base64," + base64.b64encode(payload).decode()


def multipart(fields, files=()):
    """fields: {name: value}; files: [(field name, path or (filename, bytes, mime))]. Returns (body, content type)."""
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        if v is None:
            continue
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v if isinstance(v, str) else json.dumps(v)}\r\n'.encode())
    for k, f in files:
        if isinstance(f, (str, Path)):
            f = (Path(f).name, Path(f).read_bytes(), mimetypes.guess_type(str(f))[0])
        name, payload, mime = f
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {mime or "application/octet-stream"}\r\n\r\n'.encode()
                   + payload + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def uri_bytes(uri):
    """A data URI or a link as (bytes, mime, filename): for providers that want files uploaded as form fields."""
    if uri.startswith("data:"):
        head, _, b64 = uri.partition(",")
        mime = head[5:].split(";")[0]
        return base64.b64decode(b64), mime, "file" + (mimetypes.guess_extension(mime) or "")
    with urllib.request.urlopen(urllib.request.Request(uri, headers={"User-Agent": UA}), timeout=120) as r:
        return r.read(), r.headers.get_content_type(), Path(urllib.parse.urlparse(uri).path).name or "file"


MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp4", ".webm", ".mov", ".mkv", ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".glb", ".svg")
MEDIA_KEYS = {"url", "image", "images", "video", "videos", "audio", "output", "outputs", "image_url", "video_url", "audio_url", "image_urls",
              "video_urls", "result_urls", "resulturls", "sample", "uri", "file_url", "download_url", "imageurl", "videourl", "audiourl"}


def media_urls(node, key=""):
    """Every output link or data URI in a reply: strings under a media-ish key, or links ending in a media extension."""
    if isinstance(node, dict):  # details that echo the inputs back aren't outputs
        return [u for k, v in node.items() if k.lower() not in ("metadata", "input", "inputs", "input_videos", "input_images", "request") for u in media_urls(v, k.lower())]
    if isinstance(node, list):
        return [u for v in node for u in media_urls(v, key)]
    if isinstance(node, str):
        if node.startswith("data:") and ";base64," in node[:80]:
            return [node]
        if node.startswith("http") and (key in MEDIA_KEYS or urllib.parse.urlparse(node).path.lower().endswith(MEDIA_EXT)):
            return [node]
    return []


def scrub(node):
    """Drop inline file data from a reply before it's kept in history."""
    if isinstance(node, dict):
        return {k: scrub(v) for k, v in node.items()}
    if isinstance(node, list):
        return [scrub(v) for v in node]
    if isinstance(node, str) and len(node) > 2000 and (node.startswith("data:") or re.fullmatch(r"[A-Za-z0-9+/=\s]+", node[:200])):
        return "[file]"
    return node


# ---------- settings schemas ----------
# The app's forms read plain JSON schema: properties with type / enum / default / minimum / maximum / description.
# File fields are marked with _fal_ui_field so they get an upload box.

def snake(name):
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def file_kind(name, p):
    allowed = " ".join((p.get("x-file-metadata") or {}).get("allowed-types") or [])
    for kind in ("image", "video", "audio"):
        if kind in allowed:
            return kind
    words = snake(name).split("_")
    # settings *about* files (num_images, image_size, video_duration, generate_audio…) aren't files
    if words[-1] == "prompt" or set(words) & {"size", "count", "num", "format", "resolution", "ratio", "strength", "steps", "guidance", "scale", "width",
                                               "height", "quality", "fidelity", "weight", "type", "mode", "name", "detection", "enable", "disable",
                                               "generate", "duration", "length", "fps", "volume", "id", "ids", "position", "index", "loras"}:
        return None
    if set(words) & {"video", "videos", "clip", "clips"}:
        return "video"
    if set(words) & {"audio", "audios", "sound", "music", "speech"} or (words[0] == "voice" and words[-1] == "url"):
        return "audio"
    if set(words) & {"image", "images", "img", "imgs", "frame", "frames", "mask", "photo", "picture", "face", "init", "keyframe", "keyframes", "subject"}:
        return "image"
    return None


def simplify(p):
    """One schema property in the shapes the app's forms handle."""
    if not isinstance(p, dict):
        return p
    p = dict(p)
    if isinstance(p.get("allOf"), list) and len(p["allOf"]) == 1:
        p = {**p.pop("allOf")[0], **p}
    opts = [o for o in (p.get("anyOf") or p.get("oneOf") or []) if isinstance(o, dict) and o.get("type") != "null"]
    if opts and not p.get("type"):
        # a value that may come in several string forms (a link, an upload id, a data URI…) is just a string
        flat = [o for o in opts for o in ([o] + [x for x in (o.get("anyOf") or o.get("oneOf") or []) if isinstance(x, dict)])]
        if all(o.get("type", "string") == "string" and "properties" not in o and "items" not in o for o in flat):
            enums = [v for o in flat for v in o.get("enum", [])] + [o["const"] for o in flat if "const" in o]
            p = {k: v for k, v in p.items() if k not in ("anyOf", "oneOf")} | {"type": "string"} | ({"enum": enums} if enums else {})
        else:
            stringy = lambda o: o.get("type") == "string" or (not o.get("type") and all(x.get("type", "string") == "string" for x in o.get("anyOf") or o.get("oneOf") or [o]))
            first = next((o for o in opts if stringy(o)), None) or next((o for o in opts if o.get("type") == "array"), None)
            if first:  # e.g. "one image link, or a list of image objects": offer the simple form
                p = {k: v for k, v in p.items() if k not in ("anyOf", "oneOf")} | simplify(first) | {"description": p.get("description") or first.get("description", "")}
    if "const" in p and "enum" not in p:
        p["enum"] = [p.pop("const")]
    if p.get("type") == "array" and isinstance(p.get("items"), dict):
        p["items"] = simplify(p["items"])
    if isinstance(p.get("type"), list):  # ["string", "null"]
        types = [t for t in p["type"] if t != "null"]
        p["type"] = types[0] if len(types) == 1 else p["type"]
    for k in ("examples", "example", "x-apidog-orders", "x-apidog-ignore-properties", "x-apidog-refs", "x-apidog-enum", "x-ui-metadata"):
        p.pop(k, None)
    return p


DROP = re.compile(r"^(webhook|webhook_?url|callback_?url|call_?back_?url|callback|enable_sync_mode|sync_mode|enable_base64_output|response_format|"
                  r"delivery_?method|include_?cost|task_?uuid|task_?type|upload_?endpoint|output_?type|webhook_?events|return_?base64)$", re.I)


def normalize(schema, order=None):
    """Clean a model's settings schema: simple field shapes, upload boxes for file fields, no plumbing fields."""
    schema = simplify(schema or {})
    props = {}
    for k, p in (schema.get("properties") or {}).items():
        if DROP.match(k) or not isinstance(p, dict) or ((p.get("x-ui-metadata") or {}).get("hidden")):
            continue
        p = simplify(p)
        kind = file_kind(k, p)
        items = p.get("items") if p.get("type") == "array" else None
        if isinstance(items, dict) and items.get("type") == "object" and {"uri", "url"} & set(items.get("properties") or {}):
            # a list of {uri: …} objects (Runway, Luma…): offer a file list; the provider wraps each link back up
            p = {**p, "items": {"type": "string"}, "x-wrap": "uri" if "uri" in items["properties"] else "url"}
            kind = kind or "image"
        target = p["items"] if p.get("type") == "array" and isinstance(p.get("items"), dict) else p
        if kind and target.get("type", "string") == "string" and "enum" not in target:
            target["_fal_ui_field"] = kind
            if isinstance(p.get("default"), str) and p["default"].startswith("http"):
                p.pop("default")  # sample links, not something to send by default
        if p.get("type") == "array" and isinstance(p.get("default"), list) and any(isinstance(v, str) and v.startswith("http") for v in p["default"]):
            p.pop("default")
        props[k] = p
    out = {"type": "object", "properties": props, "required": [r for r in schema.get("required", []) if r in props]}
    if order:
        out["x-fal-order-properties"] = [k for k in order if k in props] + [k for k in props if k not in order]
    return out


def resolve(node, comps, depth=0):
    """Inline $ref links (OpenAPI #/components/schemas/X)."""
    if depth > 25:
        return node
    if isinstance(node, dict):
        if "$ref" in node:
            target = comps.get(node["$ref"].split("/")[-1], {})
            return resolve({**target, **{k: v for k, v in node.items() if k != "$ref"}}, comps, depth + 1)
        return {k: resolve(v, comps, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(v, comps, depth + 1) for v in node]
    return node


def fal_schema(model):
    """A fal model's input schema from fal's public OpenAPI page (no key needed)."""
    url = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=" + urllib.parse.quote(model, safe="/")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
            spec = json.load(r)
    except urllib.error.HTTPError:
        spec = {}
    paths = spec.get("paths", {})
    post = (paths.get(f"/{model}") or next((p for p in paths.values() if "post" in p), {})).get("post")
    if not post:
        raise RuntimeError(f"fal has no input schema for '{model}'. Check the model id on its fal.ai page.")
    ref = post.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    return resolve(ref, spec.get("components", {}).get("schemas", {}))


# fal's pricing API units -> the price comparison's units
FAL_UNITS = {"image": "image", "images": "image", "megapixel": "megapixel", "megapixels": "megapixel", "second": "second", "seconds": "second",
             "video": "clip", "videos": "clip", "5 seconds": "clip", "processed megapixels": "megapixel", "units": "run", "1": "run", "request": "run",
             "requests": "run", "generation": "run", "generations": "run", "run": "run"}


def fal_price(row):
    """One row of fal's pricing API as a cost, or None if its unit isn't one the app can estimate."""
    unit, usd = str(row.get("unit", "")).lower(), row.get("unit_price")
    if unit == "minutes" and usd:
        unit, usd = "second", usd / 60
    if unit == "steps":  # training: priced by the steps asked for
        return cost(usd, "step") if row.get("currency", "USD") == "USD" else None
    if unit == "1000 characters":  # speech: priced by the length of the text
        return cost(usd, "kchar") if row.get("currency", "USD") == "USD" else None
    if unit == "compute seconds" and usd:  # ponytail: the machine time isn't known up front; a minute is far more than a join or trim takes
        unit, usd = "run", usd * 60
    return cost(usd, FAL_UNITS[unit]) if row.get("currency", "USD") == "USD" and unit in FAL_UNITS else None


def openapi_variants(spec, path, model_key="model"):
    """The models one OpenAPI POST path serves: [(model id or None, request schema)].
    Handles a oneOf per model (Runway, SiliconFlow), one schema with a model enum (one entry per value), or no model field."""
    comps = (spec.get("components") or {}).get("schemas") or {}
    post = ((spec.get("paths") or {}).get(path) or {}).get("post") or {}
    body = (((post.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
    body = resolve(body, comps)
    variants = body.get("oneOf") or body.get("anyOf") or [body]
    out = []
    for v in variants:
        if v.get("allOf"):
            merged = {"properties": dict(v.get("properties") or {}), "required": list(v.get("required") or [])}
            for part in v["allOf"]:
                merged["properties"].update(part.get("properties") or {})
                merged["required"] += part.get("required") or []
            v = {**v, **merged}
        props = v.get("properties") or {}
        m = props.get(model_key) or {}
        ids = m.get("enum") or ([m["const"]] if "const" in m else []) or ([m["default"]] if m.get("default") else []) or [v.get("title")] if m else [None]
        rest = {**v, "properties": {k: p for k, p in props.items() if k != model_key}, "required": [r for r in v.get("required", []) if r != model_key]}
        out += [(i, rest) for i in ids]
    return out


def catalog(name):
    """A bundled catalog (built by tools/build_catalogs.py): id -> {name, cat, desc, path, schema…}."""
    f = Path(__file__).parent / "catalogs" / f"{name}.json"
    return {r["id"]: r for r in json.loads(f.read_text(encoding="utf-8"))} if f.exists() else {}


def cost(usd, per="run"):
    """A model's list price in a form the price comparison understands: per run, image, second, megapixel,
    or clip (a video at its default length, about 5 seconds)."""
    try:
        usd = float(usd)
    except (TypeError, ValueError):
        return None
    return {"usd": usd, "per": per} if usd > 0 else None


def amount(node, keys=("total", "price", "cost", "amount", "usd")):
    """The dollar figure in a price reply, wherever the provider puts it (prefers totals)."""
    found = []

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k.lower())
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, (int, float)) and not isinstance(x, bool) and any(w in key for w in keys) and "discount" not in key and "rate" not in key:
            found.append((next(i for i, w in enumerate(keys) if w in key), float(x)))
    walk(node)
    return min(found)[1] if found else None


def price(p):
    try:
        return f"${float(p):.4f}".rstrip("0").rstrip(".") if p not in (None, "") else ""
    except (TypeError, ValueError):
        return str(p) if p else ""


# builders for providers whose settings are written out here by hand
def S(required=("prompt",), order=None, **props):
    return normalize({"type": "object", "properties": props, "required": list(required)}, order or list(props))


def T(desc="", default=None, **kw):
    return {"type": "string", "description": desc, **({"default": default} if default is not None else {}), **kw}


def N(lo=None, hi=None, default=None, desc="", integer=True):
    p = {"type": "integer" if integer else "number", "description": desc}
    p.update({k: v for k, v in (("minimum", lo), ("maximum", hi), ("default", default)) if v is not None})
    return p


def E(values, default=None, desc=""):
    return {"type": "string" if all(isinstance(v, str) for v in values) else "integer", "enum": list(values), "description": desc,
            **({"default": default} if default is not None else {})}


def B(default=None, desc=""):
    return {"type": "boolean", "description": desc, **({"default": default} if default is not None else {})}


def F(kind="image", desc="", many=0):
    """A file field: one file, or a list of up to `many`."""
    one = {"type": "string", "_fal_ui_field": kind, "description": desc}
    return {"type": "array", "items": one, "maxItems": many, "description": desc} if many else one
