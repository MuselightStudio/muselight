"""Hugging Face Inference Providers: one Hugging Face token runs models hosted by fal, WaveSpeed, Replicate or Hugging Face
itself, billed to your Hugging Face account (Pro includes monthly credits)."""
import json, urllib.parse, urllib.request
from . import _core as core

ID, LABEL, GROUP = "huggingface", "Hugging Face", "market"
KEYS = ["HF_TOKEN"]
LINK, BILLING = "https://huggingface.co/settings/tokens", "huggingface.co/settings/billing"
HELP = "One Hugging Face token (with 'Make calls to Inference Providers' allowed) runs popular models from several hosts; Pro accounts get monthly credits."
ROUTER, HUB = "https://router.huggingface.co", "https://huggingface.co/api"
TASKS = ("text-to-image", "image-to-image", "text-to-video", "image-to-video")
SUPPORTED = ("fal-ai", "wavespeed", "replicate", "hf-inference")  # hosts whose request format this app speaks
call = core.caller(__name__)
mapping, schemas = {}, {}  # model -> (host, host's model id, task)


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": core.UA}), timeout=60) as r:
        return json.load(r)


def _route(m):
    maps = m.get("inferenceProviderMapping") or []
    if isinstance(maps, dict):  # one model's page lists hosts as {name: details}
        maps = [{"provider": k, **v} for k, v in maps.items()]
    for host in SUPPORTED:
        for p in maps:
            if p.get("provider") == host and p.get("status") == "live" and p.get("task") in TASKS:
                return host, p["providerId"], p["task"]


def models():
    out = []
    for task in TASKS:
        rows = _get(f"{HUB}/models?inference_provider=all&pipeline_tag={task}&sort=likes&limit=60&expand[]=inferenceProviderMapping&expand[]=likes")
        for m in rows:
            r = _route(m)
            if r and m["id"] not in mapping:
                mapping[m["id"]] = r
                out.append({"id": m["id"], "name": m["id"].split("/")[-1], "cat": r[2], "desc": f"Runs on {r[0]} through Hugging Face · {m.get('likes', 0)} likes"})
    return out


def _mapped(mid):
    if mid not in mapping:
        r = _route(_get(f"{HUB}/models/{mid}?expand[]=inferenceProviderMapping"))
        if not r:
            raise RuntimeError(f"No host this app supports runs '{mid}' through Hugging Face.")
        mapping[mid] = r
    return mapping[mid]


GENERIC = {
    "text-to-image": dict(prompt=core.T("What to make."), negative_prompt=core.T("What to avoid."), width=core.N(256, 2048), height=core.N(256, 2048),
                          num_inference_steps=core.N(1, 100), guidance_scale=core.N(0, 30, integer=False), seed=core.N(0, 2 ** 32)),
    "text-to-video": dict(prompt=core.T("What to make."), negative_prompt=core.T("What to avoid."), num_frames=core.N(1, 300), seed=core.N(0, 2 ** 32)),
}
GENERIC["image-to-image"] = {**GENERIC["text-to-image"], "image": core.F("image", "The image to work from.")}
GENERIC["image-to-video"] = {**GENERIC["text-to-video"], "image": core.F("image", "The first frame.")}


def schema(mid):
    if mid not in schemas:
        host, pid, task = _mapped(mid)
        if host == "fal-ai":  # fal publishes each model's settings
            spec = _get("https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=" + urllib.parse.quote(pid, safe="/"))
            variants = core.openapi_variants(spec, "/" + pid)
            if variants:
                schemas[mid] = core.normalize(variants[0][1])
                return schemas[mid]
        schemas[mid] = core.S(**GENERIC[task])
    return schemas[mid]


def _under(host, url):
    p = urllib.parse.urlparse(url)
    return f"{ROUTER}/{host}{p.path}" + (f"?{p.query}" if p.query else "")


def run(mid, body, job):
    host, pid, task = _mapped(mid)
    if host == "hf-inference":
        prompt = body.pop("prompt", "")
        payload = call(f"{ROUTER}/hf-inference/models/{pid}", {"inputs": prompt, "parameters": body}, timeout=600)
        if isinstance(payload, tuple):
            return {"model": pid}, [core.bytes_uri(*payload)]
        raise RuntimeError(f"Hugging Face: {payload}")
    if host == "fal-ai":
        d = call(f"{ROUTER}/fal-ai/{pid}?_subdomain=queue", body)
        path = urllib.parse.urlparse(d["response_url"]).path
        status, result = f"{ROUTER}/fal-ai{path}/status?_subdomain=queue", f"{ROUTER}/fal-ai{path}?_subdomain=queue"
        done = lambda: (call(status).get("status") == "COMPLETED") or None
    elif host == "wavespeed":
        d = core.unwrap(call(f"{ROUTER}/wavespeed/api/v3/{pid}", body))
        result = _under("wavespeed", d["urls"]["get"])
        done = None
    else:  # replicate
        d = call(f"{ROUTER}/replicate/v1/models/{pid}/predictions", {"input": body})
        result = _under("replicate", d["urls"]["get"])
        done = None
    job["request_id"] = d.get("request_id") or d.get("id")

    def check():
        if done:
            if not done():
                return None
            r = call(result)
            return r, core.media_urls(r)
        r = core.unwrap(call(result))
        st = str(r.get("status", "")).lower()
        if st in ("completed", "succeeded"):
            return r, core.media_urls(r.get("outputs") if "outputs" in r else r.get("output"), "output")
        if st in ("failed", "canceled", "cancelled"):
            raise RuntimeError(f"Hugging Face ({host}): {r.get('error') or st}")
    return core.wait(job, check, LABEL)


def test():
    return f"Connected as {call(f'{HUB}/whoami-v2').get('name', 'you')}"
