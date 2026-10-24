"""Every generation provider besides fal, one module each, behind one small interface the app uses.

Model ids carry the provider as a prefix ("runware:flux-1-schnell", "runpod:wan-2-5"); ids without a known prefix are fal models.
A provider's models show up once its key is saved in Connections (with "Use my own provider accounts" on).

Each provider module has: ID, LABEL, GROUP, KEYS (env names; URLS for address settings), LINK, HELP, BILLING,
headers(), models(), schema(model id), run(model id, settings, job) -> (reply, output links/data URIs) or None if cancelled, test(),
and optionally FILES = "upload" with upload(path) when it wants links instead of inline files, and ready() for custom setup checks.
"""
import os, time
from types import SimpleNamespace

from . import _core as core
from . import (atlas, bfl, byteplus, comfyui, dashscope, deepinfra, google, huggingface, ideogram, kie, kling, luma, minimax, muselight,
               openai_images, piapi, recraft, replicate, runpod, runware, runway, segmind, siliconflow, stability, together, wavespeed, xai)

MODULES = {m.ID: m for m in (muselight, wavespeed, atlas, replicate, runware, kie, piapi, segmind, deepinfra, together, siliconflow, huggingface,
                             google, openai_images, xai, bfl, byteplus, dashscope, kling, minimax, luma, runway, ideogram, recraft, stability,
                             runpod, comfyui)}
GROUPS = {"muselight": "Muselight Credits (one balance, no provider accounts)", "market": "Image & video marketplaces (many models, one key)",
          "maker": "Direct from the model makers", "own": "Your own GPUs (free on your PC, or rented)"}
fal = SimpleNamespace(LABEL="fal", BILLING="fal.ai/dashboard/billing", headers=lambda: {"Authorization": "Key " + core.key("FAL_KEY")})


def init(data_dir):
    core.DATA = data_dir


def split(model):
    p, sep, rest = model.partition(":")
    return (p, rest) if sep and p in MODULES else ("fal", model)


def label(prov):
    return "fal" if prov == "fal" else MODULES[prov].LABEL


ONLY = None  # the providers the app may use; None = all. Muselight Credits mode sets {"muselight"}: other accounts then count as not connected


def has_key(prov):
    if ONLY is not None and prov not in ONLY:
        return False
    if prov == "fal":
        return bool(core.key("FAL_KEY"))
    m = MODULES[prov]
    return m.ready() if hasattr(m, "ready") else all(core.key(k) for k in m.KEYS)


def connected():
    return ["fal"] * has_key("fal") + [p for p in MODULES if has_key(p)]


def connections(existing=()):
    """Keys and addresses for the Connections window, grouped. Keys the app already lists (e.g. OpenAI for the assistant) aren't repeated."""
    out = []
    for g in GROUPS:
        for m in MODULES.values():
            if m.GROUP != g:
                continue
            kind = getattr(m, "KIND", "key")
            for i, k in enumerate(m.KEYS):
                if k in existing:
                    continue
                label = m.LABEL if len(m.KEYS) == 1 else f"{m.LABEL} · {k.split('_', 1)[1].replace('_', ' ').lower()}"
                out.append({"name": k, "label": label, "group": GROUPS[g], "kind": kind, "link": m.LINK, "help": m.HELP if i == 0 else "",
                            "default": getattr(m, "DEFAULT", None), "provider_id": m.ID})
            for k, default in getattr(m, "URLS", {}).items():
                out.append({"name": k, "label": f"{m.LABEL} · address", "group": GROUPS[g], "kind": "url", "link": m.LINK, "help": "",
                            "default": default, "provider_id": m.ID})
    return out


def provider_of_key(name):
    return next((m.ID for m in MODULES.values() if name in m.KEYS or name in getattr(m, "URLS", {})), None)


def list_models(prov):
    m = MODULES[prov]
    out = []
    for item in m.models():
        item = dict(item)
        item["id"] = f"{prov}:{item['id']}"
        item["cat"] = f"{m.LABEL} · {item.get('cat') or ''}".rstrip(" ·")
        pr = str(item.get("price") or "")
        if pr:
            item["desc"] = (f"From {pr} per run. " if pr.startswith("$") and " per " not in pr else f"{pr}. ") + str(item.get("desc") or "")
        item.setdefault("thumb", "")
        item.setdefault("date", "")
        out.append(item)
    return out


def schema(model):
    prov, mid = split(model)
    return MODULES[prov].schema(mid)


uploaded = {}  # (provider, file, size, modified) -> (time, link): a quote then the run, or a batch, uploads each file once


def local_value(prov, path):
    """How a file from this PC is sent: uploaded first (providers that want links) or inline as a data URI."""
    m = MODULES.get(prov)
    if getattr(m, "FILES", "") != "upload":
        return core.datauri(path)
    st = os.stat(path)
    key = (prov, str(path), st.st_size, st.st_mtime)
    if key not in uploaded or time.time() - uploaded[key][0] > 3600:  # providers' upload links expire after a while
        uploaded[key] = (time.time(), m.upload(path))
    return uploaded[key][1]


def run(model, body, job):
    prov, mid = split(model)
    got = MODULES[prov].run(mid, body, job)
    if got is None:
        return None
    result, outs = got
    return core.scrub(result), [o for o in outs if o]


def test(prov):
    return MODULES[prov].test()


def api_error(prov, code, text):
    m = fal if prov == "fal" else MODULES[prov]
    return core.api_error(m.LABEL, m.BILLING, code, text)


def call(prov, url, body=None, method=None):
    return core.http(fal if prov == "fal" else MODULES[prov], url, body, method=method)


def selftest():
    assert split("wavespeed:a/b") == ("wavespeed", "a/b") and split("fal-ai/flux/dev") == ("fal", "fal-ai/flux/dev") and split("fal:x") == ("fal", "fal:x")
    assert "out of credit" in api_error("wavespeed", 402, '{"message":"x"}') and "Atlas Cloud didn't accept" in api_error("atlas", 401, "{}")
    assert api_error("fal", 422, '{"detail":[{"loc":["body","prompt"],"msg":"Field required"}]}') == "fal didn't accept these settings: prompt: Field required"
    assert core.price("0.0030") == "$0.003" and core.price(None) == ""
    assert core.amount({"quote": {"total_usd": 0.08, "unit_price": 0.04, "discount_rate": 90}}) == 0.08 and core.amount({"data": {"price": 0.45}}) == 0.45
    for m in MODULES.values():  # every provider is complete
        for attr in ("ID", "LABEL", "GROUP", "KEYS", "LINK", "HELP", "headers", "models", "schema", "run", "test"):
            assert hasattr(m, attr), (m.ID, attr)
        assert m.GROUP in GROUPS, m.ID
    # schema cleanup: file fields get upload boxes, plumbing fields go, sample links aren't defaults
    s = core.normalize({"properties": {"image_url": {"type": "string", "default": "https://x/y.png"}, "num_images": {"type": "integer"},
                                       "webhook": {"type": "string"}, "frameImages": {"type": "array", "items": {"type": "string"}},
                                       "promptImage": {"anyOf": [{"type": "string", "pattern": "^https"}, {"type": "string", "pattern": "^data:"}]},
                                       "aspect": {"anyOf": [{"const": "a"}, {"const": "b"}]}}, "required": ["image_url", "webhook"]})
    p = s["properties"]
    assert p["image_url"]["_fal_ui_field"] == "image" and "default" not in p["image_url"] and "_fal_ui_field" not in p["num_images"]
    assert "webhook" not in p and s["required"] == ["image_url"] and p["frameImages"]["items"]["_fal_ui_field"] == "image"
    assert p["promptImage"]["type"] == "string" and p["promptImage"]["_fal_ui_field"] == "image" and p["aspect"]["enum"] == ["a", "b"]
    v = core.openapi_variants({"paths": {"/x": {"post": {"requestBody": {"content": {"application/json": {"schema": {"oneOf": [
        {"properties": {"model": {"const": "m1"}, "a": {"type": "string"}}, "required": ["model", "a"]},
        {"properties": {"model": {"enum": ["m2", "m3"]}, "b": {"type": "integer"}}}]}}}}}}}}, "/x")
    assert [i for i, _ in v] == ["m1", "m2", "m3"] and v[0][1]["required"] == ["a"] and "model" not in v[0][1]["properties"]
    assert core.media_urls({"images": [{"url": "https://a/b"}], "prompt": "https://not-media", "x": "data:image/png;base64,AAAA"}) == ["https://a/b", "data:image/png;base64,AAAA"]
    # ComfyUI: a workflow's settings are found, and filled in on a copy
    wf = {"3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 7, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
          "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
          "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["4", 1]}},
          "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
          "8": {"class_type": "LoadImage", "inputs": {"image": "x.png"}}, "9": {"class_type": "Foo", "inputs": {"level": 3}, "_meta": {"title": "@style"}}}
    sch, mapping = comfyui.parse(wf)
    assert set(sch["properties"]) >= {"prompt", "negative_prompt", "seed", "steps", "cfg", "width", "height", "image", "style"}, sch["properties"].keys()
    filled = comfyui.fill(wf, {"prompt": "dog", "image": "data:image/png;base64,AA", "style": 5}, lambda v: "uploaded.png")
    assert filled["6"]["inputs"]["text"] == "dog" and filled["8"]["inputs"]["image"] == "uploaded.png" and filled["9"]["inputs"]["level"] == 5
    assert filled["3"]["inputs"]["seed"] != 1 and wf["6"]["inputs"]["text"] == "cat"  # random seed; the original is untouched
    for name, wf in comfyui.starters().items():
        assert {"prompt", "seed"} <= set(comfyui.parse(wf)[0]["properties"]), name
    assert len(core.catalog("kie")) > 50 and len(core.catalog("piapi")) > 20
    # assistant models: a pasted link picks its own source
    from . import runpod
    ref = runpod.model_ref
    assert ref("Qwen/Qwen3-8B") == ("huggingface", "Qwen/Qwen3-8B", "https://huggingface.co")
    assert ref("https://huggingface.co/Qwen/Qwen3-8B/tree/main")[1] == "Qwen/Qwen3-8B"
    assert ref("https://huggingbay.xyz/artifacts/hf-model-qwen-qwen3-8b")[:2] == ("huggingbay", "hf-model-qwen-qwen3-8b")
    assert ref("https://www.modelscope.cn/models/Qwen/Qwen3-8B")[:2] == ("modelscope", "Qwen/Qwen3-8B")
    assert ref("https://hf-mirror.com/Qwen/Qwen3-8B") == ("mirror", "Qwen/Qwen3-8B", "https://hf-mirror.com")
    assert ref("Qwen/Qwen3-8B", "huggingbay")[0] == "huggingbay"
    print("providers selftest ok")
