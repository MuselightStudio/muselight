"""RunPod: ready-made pay-per-use models, plus your own GPUs.

- Public endpoints: hosted models (Flux, Wan, Seedance, Kling…) billed per output. Listed with their settings.
- Your serverless endpoints: a ComfyUI endpoint (one click, scales to zero) runs the starter workflow for its model
  and every workflow you've added; any other endpoint takes raw JSON input. A vLLM endpoint can power the assistant.
- Pods: an always-on GPU running the ComfyUI app, usable as the app's ComfyUI server.
"""
import base64, json, os, re, time, urllib.error, urllib.parse, urllib.request
from . import _core as core
from . import comfyui

ID, LABEL, GROUP = "runpod", "RunPod", "own"
KEYS = ["RUNPOD_API_KEY"]
LINK, BILLING = "https://console.runpod.io/user/settings", "console.runpod.io/user/billing"
HELP = ("Ready-made models paid per result, plus your own GPUs: one-click ComfyUI endpoints that cost nothing while idle, "
        "an assistant model you host yourself, and pods. Manage them under GPUs.")
SL, REST, GQL = "https://api.runpod.ai/v2", "https://api.runpod.io/v2", "https://api.runpod.io/graphql"
call = core.caller(__name__)
cache = {}  # name -> (time, value)
COMFY_VARIANTS = {"flux1-schnell": "FLUX.1 schnell (fast, 24 GB)", "flux1-dev-fp8": "FLUX.1 dev (24 GB)", "sdxl": "Stable Diffusion XL (16 GB+)",
                  "sd3": "Stable Diffusion 3 medium (16 GB+)"}
# models the assistant can use with tools; the parser tells vLLM how that model writes tool calls
LLM_MODELS = {"Qwen/Qwen3-8B": ("hermes", "qwen3", 24), "Qwen/Qwen3-14B": ("hermes", "qwen3", 48), "Qwen/Qwen3-32B-AWQ": ("hermes", "qwen3", 48),
              "meta-llama/Llama-3.1-8B-Instruct": ("llama3_json", "", 24), "mistralai/Mistral-Small-3.2-24B-Instruct-2506": ("mistral", "", 80)}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def cached(name, fn, ttl=60):
    t, v = cache.get(name, (0, None))
    if time.time() - t > ttl:
        v = fn()
        cache[name] = (time.time(), v)
    return v


def gql(query, variables=None, auth=True):
    r = call(GQL, {"query": query, "variables": variables or {}}, auth=auth)
    if r.get("errors"):
        raise RuntimeError("RunPod: " + "; ".join(e.get("message", "") for e in r["errors"]))
    return r["data"]


# ---------- catalog ----------

def public():
    """Ready-made public endpoints: id -> config (with its parsed settings)."""
    def load():
        rows = gql("query { allAiApiPublicConfigs { aiApiId displayName description metadata isLive schema } }", auth=False)["allAiApiPublicConfigs"]
        out = {}
        for c in rows:
            meta = json.loads(c.get("metadata") or "{}")
            if c.get("isLive") and meta.get("source") != "language":
                out[c["aiApiId"]] = {**c, "meta": meta}
        return out
    return cached("public", load, 3600)


def endpoints():
    return cached("endpoints", lambda: call(f"{REST}/serverless").get("endpoints", []), 30)


def kind_of(ep):
    img = (ep.get("image") or "") + " " + json.dumps(ep.get("env") or {})
    if "worker-comfyui" in img:
        return "comfy"
    if "vllm" in img or "MODEL_NAME" in img:
        return "llm"
    return "other"


def comfy_variant(ep):
    m = re.search(r"worker-comfyui:[\d.]+-([a-z0-9-]+)$", ep.get("image") or "")
    return m.group(1) if m else None


def comfy_flows(ep):
    return {**comfyui.starters(comfy_variant(ep)), **comfyui.workflows()}


def models():
    out = []
    for aid, c in sorted(public().items(), key=lambda kv: kv[1]["displayName"]):
        meta = c["meta"]
        out.append({"id": aid, "name": c["displayName"], "cat": "ready-made · " + (meta.get("tag") or meta.get("source") or ""),
                    "desc": ((meta.get("priceString") + ". ") if meta.get("priceString") else "") + (c.get("description") or "")[:180],
                    "cost": core.cost(meta.get("cost"), "megapixel" if meta.get("pricingModel") == "per-pixel" else "clip" if meta.get("source") == "video" else "run")})
    try:
        eps = endpoints()
    except Exception:
        eps = []
    for ep in eps:
        if kind_of(ep) == "comfy":
            for name in comfy_flows(ep):
                out.append({"id": f"{ep['id']}/{name}", "name": f"{ep.get('name') or ep['id']} · {name}", "cat": "your GPU · ComfyUI",
                            "desc": "Runs on your RunPod endpoint; costs only while it works."})
        elif kind_of(ep) == "other":
            out.append({"id": ep["id"], "name": ep.get("name") or ep["id"], "cat": "your GPU · endpoint", "desc": "Your RunPod endpoint: send its input as JSON."})
    return out


def _public_schema(c):
    raw = json.loads(c.get("schema") or "{}")
    props, req = {}, []
    for k, p in raw.items():
        p = dict(p)
        if p.pop("required", False):
            req.append(k)
        if "prompt" in k and p.get("type") == "string" and "enum" not in p:
            p.pop("default", None)  # sample prompts, not settings
        props[k] = p
    return core.normalize({"type": "object", "properties": props, "required": req}, list(raw))


def schema(mid):
    if "/" in mid:
        ep_id, flow = mid.split("/", 1)
        ep = next((e for e in endpoints() if e["id"] == ep_id), None)
        wf = comfy_flows(ep).get(flow) if ep else None
        if wf is None:
            raise RuntimeError(f"No ComfyUI workflow '{flow}' for RunPod endpoint {ep_id}.")
        return comfyui.parse(wf)[0]
    if mid in public():
        return _public_schema(public()[mid])
    return {"type": "object", "properties": {"input": {"type": "object", "description": "The JSON your endpoint's handler expects as its input."}},
            "required": ["input"]}


def _outputs(out):
    files = []
    if isinstance(out, dict) and isinstance(out.get("images"), list):  # the ComfyUI worker: base64 or bucket links
        for f in out["images"]:
            if isinstance(f, dict) and f.get("data"):
                files.append(f["data"] if f.get("type") == "s3_url" else
                             core.bytes_uri(__import__("base64").b64decode(f["data"]), __import__("mimetypes").guess_type(f.get("filename", "x.png"))[0]))
    return files or core.media_urls(out, "output")


def run(mid, body, job):
    if "/" in mid:
        ep_id, flow = mid.split("/", 1)
        schema(mid)
        images = []

        def put(value):
            name = f"input_{len(images) + 1}.png"
            images.append({"name": name, "image": value if value.startswith("data:") else core.bytes_uri(*core.uri_bytes(value)[:2])})
            return name
        wf = comfyui.fill(comfy_flows(next(e for e in endpoints() if e["id"] == ep_id))[flow], body, put)
        payload = {"workflow": wf, **({"images": images} if images else {})}
    else:
        ep_id = mid
        payload = body.get("input", body) if mid not in public() else body
        if isinstance(payload, str):
            payload = json.loads(payload)
    d = call(f"{SL}/{ep_id}/run", {"input": payload})
    job["request_id"] = d.get("id")

    def check():
        r = call(f"{SL}/{ep_id}/status/{d['id']}")
        st = r.get("status")
        if st == "COMPLETED":
            out = r.get("output")
            if isinstance(out, dict) and out.get("error"):
                raise RuntimeError(f"RunPod: {out['error']}")
            return core.scrub(r), _outputs(out)
        if st in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise RuntimeError(f"RunPod: {r.get('error') or st}")
        job["queue_position"] = "starting a GPU" if st == "IN_QUEUE" else None
    return core.wait(job, check, LABEL, cancel=lambda: call(f"{SL}/{ep_id}/cancel/{d['id']}", data=b"", method="POST"), every=2)


def charged(result):
    out = result.get("output")
    return out.get("cost") if isinstance(out, dict) else None


def balance():
    me = gql("query { myself { clientBalance currentSpendPerHr } }")["myself"]
    return {"balance": me.get("clientBalance"), "per_hour": me.get("currentSpendPerHr")}


def test():
    b = balance()
    return f"Connected · balance ${float(b['balance'] or 0):.2f}"


# ---------- managing your GPUs (the GPUs panel) ----------

def gpus(product="SERVERLESS"):
    """GPU choices with live stock and $/hour: serverless pools, or single GPU types for pods."""
    rows = call(f"{REST}/catalog/gpus?product={product}&include=AVAILABILITY").get("gpus", [])
    if product == "POD":
        return sorted(({"id": g["id"], "name": g.get("name") or g["id"], "memory": g.get("memory"), "stock": g.get("availability"),
                        "price": (g.get("price") or {}).get("secure") or (g.get("price") or {}).get("community")}
                       for g in rows if g.get("availability") not in (None, "NONE")), key=lambda g: (g["price"] or 99))
    pools = {}
    for g in rows:
        pool, cost = g.get("pool"), (g.get("price") or {}).get("serverless")
        if not pool or cost is None:
            continue
        p = pools.setdefault(pool, {"id": pool, "memory": g.get("memory"), "price": cost, "names": [], "stock": "NONE"})
        p["names"].append(g.get("name") or g["id"])
        p["price"] = min(p["price"], cost)
        order = ["NONE", "LOW", "MEDIUM", "HIGH"]
        if order.index(g.get("availability") or "NONE") > order.index(p["stock"]):
            p["stock"] = g.get("availability")
    return sorted(pools.values(), key=lambda p: (p["memory"] or 0, p["price"]))


def my_endpoints():
    cache.pop("endpoints", None)
    out = []
    for ep in endpoints():
        env = ep.get("env") or {}
        out.append({"id": ep["id"], "name": ep.get("name"), "kind": kind_of(ep), "image": ep.get("image"), "variant": comfy_variant(ep),
                    "model": (env.get("SERVED_MODEL_NAME") or env.get("MODEL_NAME")) if isinstance(env, dict) else None, "gpus": (ep.get("gpu") or {}).get("pools"),
                    "workers": ep.get("workers"), "flows": list(comfy_flows(ep)) if kind_of(ep) == "comfy" else []})
    return out


def _latest_tag(repo, pattern, fallback):
    try:
        req = urllib.request.Request(f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&ordering=last_updated", headers={"User-Agent": core.UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            tags = [t["name"] for t in json.load(r).get("results", []) if re.fullmatch(pattern, t["name"])]
        return max(tags, key=lambda t: [int(x) for x in re.findall(r"\d+", t)[:3]]) if tags else fallback
    except Exception:
        return fallback


def deploy_comfy(variant, pool, max_workers=2):
    if variant not in COMFY_VARIANTS:
        raise RuntimeError("Unknown ComfyUI model set")
    tag = _latest_tag("runpod/worker-comfyui", rf"\d+\.\d+\.\d+-{re.escape(variant)}", f"5.10.0-{variant}")
    ep = call(f"{REST}/serverless", {
        "name": f"muselight-comfyui-{variant}", "image": f"runpod/worker-comfyui:{tag}", "type": "QUEUE", "disk": 20,
        "gpu": {"pools": [pool], "count": 1, "minCudaVersion": "12.8"},
        "workers": {"min": 0, "max": int(max_workers), "idleTimeout": 5},  # scale to zero: nothing bills while idle
        "scaling": {"type": "QUEUE_DELAY", "queueDelay": 4}, "timeout": 900000, "flashboot": True})
    cache.pop("endpoints", None)
    return {"id": ep.get("id"), "image": f"runpod/worker-comfyui:{tag}"}


# How each model family writes tool calls (vLLM's --tool-call-parser), and its reasoning parser when it thinks out loud.
FAMILY_PARSERS = [(r"^qwen3", "hermes", "qwen3"), (r"^qwen2", "hermes", ""), (r"^llama4", "llama4_pythonic", ""), (r"^llama", "llama3_json", ""),
                  (r"^(mistral|mixtral|ministral|pixtral)", "mistral", ""), (r"^deepseek_v3", "deepseek_v3", ""), (r"^gpt_oss", "openai", ""),
                  (r"^granite", "granite", ""), (r"^glm4", "glm45", "glm45"), (r"^internlm", "internlm", ""), (r"^kimi", "kimi_k2", ""),
                  (r"^minimax", "minimax", ""), (r"^hunyuan", "hunyuan_a13b", ""), (r"^(phi3|phi4)", "phi4_mini_json", "")]
DTYPE_BYTES = {"F64": 8, "I64": 8, "F32": 4, "I32": 4, "BF16": 2, "F16": 2, "I16": 2, "F8_E4M3": 1, "F8_E5M2": 1, "I8": 1, "U8": 1}
GPU_TIERS = [16, 24, 32, 48, 80, 96, 141, 180]


# Where a model can come from. Hugging Face mirrors (anything that speaks its API, e.g. hf-mirror.com) work through HF_ENDPOINT;
# Hugging Bay and ModelScope don't, so the worker downloads their files itself (FETCH) before vLLM starts.
SOURCES = {"huggingface": "Hugging Face", "huggingbay": "Hugging Bay", "modelscope": "ModelScope", "mirror": "Hugging Face mirror"}
HB, MS = "https://huggingbay.xyz", "https://www.modelscope.cn"
MODEL_DIR = "/muselight-model"
# Runs inside the worker at boot (and here, to list files): downloads every file the model needs, checks each SHA-256, then exits.
FETCH = r"""
import hashlib, json, os, shutil, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
SKIP = (".md", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".gitattributes")
WEIGHTS = (".bin", ".pth", ".pt", ".gguf", ".onnx", ".msgpack", ".h5")

def get(url, tries=30):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Muselight/1.0"}), timeout=120)
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1 or getattr(e, "code", 500) in (401, 403, 404):
                raise
            wait = getattr(e, "headers", None) and e.headers.get("Retry-After")
            time.sleep(min(60, int(wait) if str(wait).isdigit() else 2 ** i))

def files(src, mid, tries=8):
    # [(path, url, sha256 or "", size)] for the files vLLM needs: configs, tokenizer, safetensors (other weight formats are skipped)
    q = urllib.parse.quote
    if src == "huggingbay":
        for i in range(tries):  # its manifest sometimes comes back without the file list while it re-checks: ask again
            m = json.load(get(f"https://huggingbay.xyz/api/manifests/{mid}", tries))
            if m.get("files"):
                break
            time.sleep(min(30, 2 ** i))
        out = [(f["path"], "https://huggingbay.xyz" + (f.get("download_url") or f"/api/downloads/{mid}/{q(f['path'])}"), f.get("sha256") or "", f.get("size") or 0)
               for f in m.get("files") or []]
    else:
        d = json.load(get(f"https://www.modelscope.cn/api/v1/models/{mid}/repo/files?Revision=master&Recursive=true", tries))["Data"]["Files"]
        out = [(f["Path"], f"https://www.modelscope.cn/api/v1/models/{mid}/repo?Revision=master&FilePath={q(f['Path'])}", f.get("Sha256") or "", f.get("Size") or 0)
               for f in d if f.get("Type") != "tree"]
    st = any(p.endswith(".safetensors") for p, *_ in out)
    return [f for f in out if not f[0].lower().endswith(SKIP) and not f[0].startswith("original/") and not (st and f[0].endswith(WEIGHTS))]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()

def torrent(mid, dest):
    # Hugging Bay seeds each model as a torrent (its own servers are a web seed in it): take what the swarm has with aria2.
    # Anything this misses, or that fails its checksum, is downloaded file by file afterwards.
    try:
        data = get(f"https://huggingbay.xyz/artifact/{mid}/download.torrent", 3).read()
        if not shutil.which("aria2c"):
            subprocess.run("(apt-get update -qq && apt-get install -y -qq aria2) >/dev/null 2>&1", shell=True, timeout=600)
        if not shutil.which("aria2c"):
            return print("no aria2c, downloading over HTTP", flush=True)
        t = os.path.join(dest, ".bt", "model.torrent")
        os.makedirs(os.path.dirname(t), exist_ok=True)
        open(t, "wb").write(data)
        subprocess.run(["aria2c", "--seed-time=0", "--bt-stop-timeout=300", "--file-allocation=none", "--summary-interval=60",
                        "--console-log-level=warn", "--dir", os.path.dirname(t), t], timeout=6 * 3600)
    except Exception as e:  # no torrent for this model, or the swarm failed: plain downloads still work
        print("torrent skipped:", e, flush=True)

def fetch(src, mid, dest):
    want = [f for f in files(src, mid) if not os.path.exists(os.path.join(dest, f[0]) + ".ok")]  # .ok: already here from an earlier start
    if want and src == "huggingbay":
        torrent(mid, dest)
    for path, url, sha, _ in want:
        out = os.path.join(dest, path)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        got = os.path.join(dest, ".bt", mid, path)
        if os.path.exists(got) and (not sha or sha256(got) == sha.split(":")[-1]):
            os.replace(got, out)
            print("from torrent", path, flush=True)
        else:
            with get(url) as r, open(out, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 22)
            if sha and sha256(out) != sha.split(":")[-1]:
                os.remove(out)
                sys.exit(f"{path} doesn't match its published checksum: not loading it")
            print("fetched", path, flush=True)
        open(out + ".ok", "w").close()
    shutil.rmtree(os.path.join(dest, ".bt"), ignore_errors=True)

if __name__ == "__main__":
    fetch(*sys.argv[1:4])
"""
_fetch = {}
exec(FETCH, _fetch)


def _json(url, token=""):
    req = urllib.request.Request(url, headers={"User-Agent": core.UA, **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def model_ref(model, source="huggingface"):
    """(source, id, base) from what was pasted: a link picks its own source; a bare id uses the chosen one."""
    s = (model or "").strip()
    m = re.match(r"https?://([^/]+)(/.*)?$", s)
    if m:
        host, path = m.group(1).lower(), (m.group(2) or "").strip("/")
        if host.endswith("huggingbay.xyz"):
            hit = re.search(r"hf-model-[\w.-]+", path)
            source, s = "huggingbay", hit[0] if hit else path.removeprefix("models/")
        elif host.endswith(("modelscope.cn", "modelscope.ai")):
            source, s = "modelscope", path.removeprefix("models/")
        elif host.endswith("huggingface.co"):
            source, s = "huggingface", path
        else:  # any other site: a Hugging Face-compatible mirror
            return "mirror", "/".join(path.split("/")[:2]), f"https://{host}"
    elif source == "mirror":
        raise RuntimeError("For a mirror, paste the model's link on that mirror, e.g. https://hf-mirror.com/Qwen/Qwen3-8B.")
    if source == "huggingbay" and s.startswith("hf-model-"):
        return source, s, HB
    s = "/".join(s.split("/")[:2])
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", s):
        raise RuntimeError(f"Paste a {SOURCES.get(source, 'model')} id like Qwen/Qwen3-8B, or its link.")
    return source, s, {"huggingface": "https://huggingface.co", "huggingbay": HB, "modelscope": MS}[source]


def _huggingbay(mid, warn):
    """Hugging Bay's artifact id for a model, its licence and its safety verdict. Refuses a model whose scan flagged anything."""
    if not mid.startswith("hf-model-"):
        art = _json(f"{HB}/api/v1/resolve?repo={urllib.parse.quote(mid)}").get("artifact") or {}
        if not art.get("id"):
            raise RuntimeError(f"Hugging Bay has no model called {mid}.")
        mid = art["id"]
    m = _json(f"{HB}/api/manifests/{mid}")
    lic = m.get("license_clarity") or {}
    flagged = [f["path"] for f in m.get("files") or [] if f.get("scan_findings")]
    if flagged or m.get("scan_status") in ("failed", "flagged", "blocked", "malicious"):
        raise RuntimeError("Hugging Bay's safety scan flagged this model" + (f" ({', '.join(flagged[:3])})" if flagged else "") + ", so Muselight won't deploy it.")
    if m.get("serveVerdict") not in ("READY", None):
        warn.append(f"Hugging Bay says: {m.get('reason') or m.get('serveVerdict')} The worker keeps retrying when it starts.")
    if m.get("scan_status") != "passed":
        warn.append("Hugging Bay hasn't finished its safety scan of this model yet.")
    if lic.get("commercialUse") != "yes":
        warn.append(f"Licence {lic.get('license') or m.get('license') or 'unknown'}: check it allows your use. {lic.get('summary') or ''}".strip())
    try:  # whether Hugging Bay can hand out this model as a torrent right now (it doesn't for every model)
        with _fetch["get"](f"{HB}/artifact/{mid}/download.torrent", 1) as r:
            torrent = r.read(1) == b"d"  # a bencoded torrent; errors come back as JSON
    except (urllib.error.URLError, TimeoutError):
        torrent = False
    return mid, {"repo": (m.get("artifact") or {}).get("repo"), "license": lic.get("license") or m.get("license"),
                 "commercial": lic.get("commercialUse"), "scan": m.get("scan_status"), "torrent": torrent}


def inspect_llm(model, token="", source="huggingface"):
    """Everything needed to host a chat model as the assistant: where it comes from, its size, the GPU memory it needs and how it writes
    tool calls. Hugging Bay models also bring their licence and safety verdict."""
    source, mid, base = model_ref(model, source)
    hf = source in ("huggingface", "mirror")
    token = (token or os.environ.get("HF_TOKEN") or "").strip() if hf else ""
    name, extra, warn, info, cfg, sizes = SOURCES[source], {}, [], {}, {}, []
    try:
        if hf:
            info = _json(f"{base}/api/models/{mid}?expand[]=safetensors&expand[]=config&expand[]=gated&expand[]=tags&expand[]=pipeline_tag", token)
            cfg = info.get("config") or {}
            try:  # the real size: the model's weight files (compressed 4-bit/8-bit models report "unpacked" parameter counts)
                sizes = [(f.get("path", ""), f.get("size") or 0) for f in _json(f"{base}/api/models/{mid}/tree/main", token)]
            except (urllib.error.URLError, ValueError, TimeoutError):
                pass
        else:
            if source == "huggingbay":
                mid, extra = _huggingbay(mid, warn)
            listed = _fetch["files"](source, mid, 3)  # a quick check: the worker itself retries longer
            sizes = [(p, n) for p, _, _, n in listed]
            url = next((u for p, u, _, _ in listed if p == "config.json"), None)
            if not url:
                raise RuntimeError(f"{name} has no config.json for this model, so vLLM can't load it.")
            try:
                with _fetch["get"](url, 5) as r:
                    cfg = json.load(r)
            except urllib.error.HTTPError as e:  # Hugging Bay shares a few download slots between everyone: when they're full, go by the name
                if e.code not in (429, 503):
                    raise
                guess = re.sub(r"[^a-z0-9]", "", (extra.get("repo") or mid).split("/")[-1].lower())
                cfg = {"model_type": next((re.search(pat, guess)[0] for pat, _, _ in FAMILY_PARSERS if re.search(pat, guess)), "")}
                warn.append(f"{name}'s download slots are busy, so the tool-call format below is a guess from the model's name. The worker waits for a slot when it starts.")
    except urllib.error.HTTPError as e:
        if e.code in (429, 502, 503, 504):
            raise RuntimeError(f"{name} is busy right now (error {e.code}). Try Check again in a minute.")
        raise RuntimeError(f"{name} has no model called {mid}" + ((" (or it's private: add a token that can read it)." if hf else ".") if e.code in (401, 404) else f" (error {e.code})."))
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"Couldn't reach {name}: {getattr(e, 'reason', e)}")
    family = str(cfg.get("model_type") or "").lower()
    st = info.get("safetensors") or {}
    params = st.get("total") or 0
    weights = sum(n for p, n in sizes if p.endswith(".safetensors"))
    if not hf and not weights:
        raise RuntimeError(f"This model on {name} has no .safetensors weights, which the vLLM worker needs.")
    bits = (cfg.get("quantization_config") or {}).get("bits")
    weights = weights or (params * bits / 8 if bits else sum(n * DTYPE_BYTES.get(t, 2) for t, n in (st.get("parameters") or {}).items()) or params * 2)
    vram = weights / 1e9 * 1.1 + 4  # weights, plus room for a 16k-token conversation and the server itself
    parser, reasoning = next(((pa, re_) for pat, pa, re_ in FAMILY_PARSERS if re.search(pat, family)), ("hermes", ""))
    if re.search(r"deepseek.*r1", extra.get("repo") or mid, re.I):
        reasoning = "deepseek_r1"
    if not weights:
        warn.append(f"{name} doesn't list this model's size, so the GPU is a guess: pick a bigger one if it fails to start.")
    if family and not any(re.search(pat, family) for pat, _, _ in FAMILY_PARSERS):
        warn.append(f"Muselight doesn't know how '{family}' models call tools, so it tries the common format. If the assistant can't use tools, pick another model.")
    if info.get("pipeline_tag") not in (None, "text-generation", "image-text-to-text"):
        warn.append(f"This looks like a {info.get('pipeline_tag')} model, not a chat model.")
    if info.get("gated") and not token:
        warn.append("This model is gated: accept its licence on its Hugging Face page, and add a Hugging Face token (Connections → Hugging Face, or the box here).")
    if not hf:
        how = {True: " by torrent", False: " directly (Hugging Bay has no torrent for it right now; the worker tries again each start)"}.get(extra.get("torrent"), "")
        warn.append(f"Each cold start downloads the {round(weights / 1e9)} GB of weights from {name}{how}, checked against their SHA-256, so the first reply after a break is slower.")
    return {"model": mid, "source": source, "base": base, "family": family, "params_b": round(params / 1e9, 1) if params else None, "weights_gb": round(weights / 1e9, 1),
            "vram_gb": next((t for t in GPU_TIERS if t >= vram), GPU_TIERS[-1]), "too_big": vram > GPU_TIERS[-1], "parser": parser, "reasoning": reasoning,
            "gated": bool(info.get("gated")), "warnings": warn, **extra}


def deploy_llm(model, pool, max_len=16384, parser=None, reasoning=None, hf_token=None, source="huggingface", base="", weights_gb=0):
    """A vLLM endpoint from RunPod's Hub release (the same as Deploy in the console), set up for tool calling.
    Any chat model works: parser/reasoning say how it writes tool calls, source/base where it comes from (inspect_llm finds them all)."""
    listing = next((l for l in gql("query { listings(input: {}) { repoOwner repoName listedRelease { id tagName config build { imageName } } } }",
                                   auth=False)["listings"] if l["repoOwner"] == "runpod-workers" and l["repoName"] == "worker-vllm"), None)
    if not listing or not listing.get("listedRelease"):
        raise RuntimeError("RunPod's vLLM worker isn't listed on the Hub right now.")
    rel = listing["listedRelease"]
    config = json.loads(rel.get("config") or "{}")
    known = LLM_MODELS.get(model)
    parser, reasoning = (parser or (known[0] if known else "hermes")), (reasoning if reasoning is not None else (known[1] if known else ""))
    overrides = {"MODEL_NAME": model, "MAX_MODEL_LEN": str(max_len), "ENABLE_AUTO_TOOL_CHOICE": "true", "TOOL_CALL_PARSER": parser}
    start, disk = "", max(60, config.get("containerDiskInGb") or 0)
    if source == "mirror":
        if not re.fullmatch(r"https://[\w.-]+(:\d+)?", base or ""):
            raise RuntimeError("A mirror needs its address, like https://hf-mirror.com.")
        overrides["HF_ENDPOINT"] = base
    elif source in ("huggingbay", "modelscope"):  # vLLM can't download from these: the worker fetches the files, then starts vLLM on that folder
        if not re.fullmatch(r"[\w.-]+(/[\w.-]+)?", model):
            raise RuntimeError("That isn't a model id.")
        overrides.update(MODEL_NAME=MODEL_DIR, SERVED_MODEL_NAME=model.split("/")[-1])
        script = base64.b64encode(FETCH.encode()).decode()
        start = f"bash -c 'echo {script} | base64 -d > /muselight_fetch.py && python3 /muselight_fetch.py {source} {model} {MODEL_DIR} && exec python3 /src/handler.py'"
        disk = max(disk, round(float(weights_gb or 0) * 1.2) + 30)
    token = (hf_token or os.environ.get("HF_TOKEN") or "").strip() if source in ("huggingface", "mirror") else ""
    if token:  # gated models (Llama, Gemma…) download with the user's own Hugging Face token
        overrides["HF_TOKEN"] = token
    if reasoning:
        overrides["REASONING_PARSER"] = reasoning
    env = []
    for entry in config.get("env", []):
        inp, k = entry.get("input") or {}, entry["key"]
        v = overrides.pop(k, None)
        if v is None and inp.get("default") not in (None, ""):
            v = str(inp["default"]).lower() if isinstance(inp["default"], bool) else str(inp["default"])
        if v is not None:
            if inp.get("type") == "boolean" and v in ("true", "false"):
                v = inp.get("trueValue", "true") if v == "true" else inp.get("falseValue", "false")
            env.append({"key": k, "value": v})
    env += [{"key": k, "value": v} for k, v in overrides.items()]
    cuda = sorted(config.get("allowedCudaVersions") or [], key=lambda v: [int(x) for x in v.split(".")])
    name = f"muselight-assistant-{model.split('/')[-1].lower()}"[:60]
    inp = {"name": name, "hubReleaseId": rel["id"], "type": "QB", "gpuIds": pool, "gpuCount": 1, "workersMin": 0, "workersMax": 1, "idleTimeout": 60,
           "scalerType": "QUEUE_DELAY", "scalerValue": 4, "executionTimeoutMs": 600000, "flashBootType": "FLASHBOOT", "locations": None,
           "networkVolumeIds": None, "compliance": [], "modelReferences": [],
           **({"minCudaVersion": cuda[0], "allowedCudaVersions": ",".join(cuda)} if cuda else {}),
           "template": {"name": f"{name}__template__{int(time.time())}", "imageName": rel["build"]["imageName"],
                        "containerDiskInGb": disk, "containerRegistryAuthId": "", "dockerArgs": start,
                        "startScript": "", "ports": "", "env": env}}
    ep = gql("mutation saveEndpoint($input: EndpointInput!) { saveEndpoint(input: $input) { id name } }", {"input": inp})["saveEndpoint"]
    cache.pop("endpoints", None)
    return {"id": ep["id"], "name": ep["name"], "model": model, "source": source}


def delete_endpoint(ep_id):
    call(f"{REST}/serverless/{ep_id}", method="DELETE")
    cache.pop("endpoints", None)


def pods():
    out = []
    for p in call(f"{REST}/pods").get("pods", []):
        ports = " ".join(p.get("ports") or [])
        out.append({"id": p["id"], "name": p.get("name"), "status": p.get("status"), "cost": p.get("cost"), "image": p.get("image"),
                    "gpu": (p.get("gpu") or {}).get("id") or (p.get("gpu") or {}).get("name"),
                    "comfy_url": f"https://{p['id']}-8188.proxy.runpod.net" if "8188" in ports or "comfyui" in (p.get("image") or "") else None})
    return out


def pod_action(pod_id, action):
    if action not in ("start", "stop", "terminate"):
        raise RuntimeError("Unknown pod action")
    return call(f"{REST}/pods/{pod_id}/action", {"action": action})


def create_comfy_pod(gpu_id):
    # RunPod's official "ComfyUI - CUDA 12.8" template: ComfyUI starts by itself on port 8188 (no models included)
    return call(f"{REST}/pods", {"name": "muselight-comfyui", "templateId": "cw3nka7d08", "gpu": {"id": gpu_id, "count": 1}})
