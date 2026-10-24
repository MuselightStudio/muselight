"""ComfyUI on your own PC (or any ComfyUI server, e.g. a RunPod pod): each saved workflow becomes a model.

Save workflows from ComfyUI with Workflow → Export (API) into studio_data/comfy_workflows. The app finds the prompt,
negative prompt, seed, steps, size and image inputs by itself; give any other node a title starting with @ to expose
its settings too (e.g. "@style" shows that node's inputs as style settings).
"""
import copy, json, random, re, urllib.parse, uuid
from pathlib import Path
from . import _core as core

ID, LABEL, GROUP = "comfyui", "ComfyUI", "own"
KEYS = ["COMFYUI_URL"]
KIND, DEFAULT = "url", "http://127.0.0.1:8188"
LINK, BILLING = "https://www.comfy.org/download", "nowhere: it runs on your own graphics card"
HELP = ("Runs your own ComfyUI workflows for free on your graphics card, or on any ComfyUI server (e.g. a RunPod pod). "
        "Export a workflow with Workflow → Export (API) and add it under GPUs.")
STARTERS = Path(__file__).parent / "comfy_starters"
call = core.caller(__name__)
_alive = {"t": 0.0, "ok": False}


def headers():
    return {}


def base():
    return (core.key("COMFYUI_URL") or DEFAULT).rstrip("/")


def ready():
    """Saved address, or ComfyUI answering at the default one (checked in the background at most every 30 s)."""
    import threading, time
    if core.key("COMFYUI_URL"):
        return True
    if time.time() - _alive["t"] > 30:
        _alive["t"] = time.time()

        def probe():
            try:
                call(base() + "/system_stats", timeout=1)
                _alive["ok"] = True
            except Exception:
                _alive["ok"] = False
        threading.Thread(target=probe, daemon=True).start()
    return _alive["ok"]


# ---------- workflows ----------

def folder():
    d = core.DATA / "comfy_workflows"
    d.mkdir(parents=True, exist_ok=True)
    return d


def check_api_format(wf):
    if not isinstance(wf, dict) or isinstance(wf.get("nodes"), list) or not all(isinstance(v, dict) and "class_type" in v for v in wf.values()):
        raise RuntimeError("That isn't an API-format workflow. In ComfyUI use Workflow → Export (API), then add that file.")
    return wf


def workflows():
    """name -> workflow, for the user's own exported workflows."""
    out = {}
    for f in sorted(folder().glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            out[f.stem] = check_api_format(wf.get("input", {}).get("workflow", wf) if isinstance(wf, dict) else wf)
        except Exception:
            continue  # a broken file shouldn't hide the others
    return out


def starters(variant=None):
    """Bundled starter workflows for RunPod's ComfyUI images: name -> workflow (only those matching the image's model set)."""
    out = {}
    for f in sorted(STARTERS.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if variant is None or d["variant"] == variant:
            out["starter-" + d["variant"]] = d["workflow"]
    return out


def parse(wf):
    """Find a workflow's settings: (schema, mapping). mapping: field -> [(node id, input name)]."""
    props, mapping, order = {}, {}, []

    def add(name, prop, target):
        n, i = name, 2
        while n in props:
            n, i = f"{name}_{i}", i + 1
        props[n], mapping[n] = prop, [target]
        order.append(n)

    linked = lambda v: isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)
    negatives = {str(n["inputs"]["negative"][0]) for n in wf.values() if linked(n.get("inputs", {}).get("negative"))}
    nodes = sorted(wf.items(), key=lambda kv: (0, int(kv[0])) if kv[0].isdigit() else (1, kv[0]))
    for nid, n in nodes:
        ct, ins = n.get("class_type", ""), n.get("inputs", {})
        title = (n.get("_meta") or {}).get("title", "")
        if title.startswith("@"):
            label = re.sub(r"\W+", "_", title[1:].strip()).strip("_").lower() or f"node_{nid}"
            plain = [(k, v) for k, v in ins.items() if not linked(v)]
            for k, v in plain:
                kind = {bool: "boolean", int: "integer", float: "number"}.get(type(v), "string")
                add(label if len(plain) == 1 else f"{label}_{k}", {"type": kind, "default": v, "description": f"{title[1:]} · {k}"}, (nid, k))
            continue
        if "TextEncode" in ct and isinstance(ins.get("text"), str):
            neg = nid in negatives or "neg" in title.lower()
            add("negative_prompt" if neg else "prompt", core.T("What to avoid." if neg else "What to make.", ins["text"]), (nid, "text"))
        elif ct in ("LoadImage", "LoadImageMask") and isinstance(ins.get("image"), str):
            add("image", core.F("image", f"Image for '{title or ct}'."), (nid, "image"))
        elif ("LoadVideo" in ct) and isinstance(ins.get("video") or ins.get("file"), str):
            add("video", core.F("video", f"Video for '{title or ct}'."), (nid, "video" if "video" in ins else "file"))
        elif "LoadAudio" in ct and isinstance(ins.get("audio"), str):
            add("audio", core.F("audio", f"Audio for '{title or ct}'."), (nid, "audio"))
        else:
            for k, desc in (("seed", "Leave empty for a random seed each run."), ("noise_seed", "Leave empty for a random seed each run.")):
                if isinstance(ins.get(k), int):
                    add("seed", core.N(0, 2 ** 53, None, desc), (nid, k))
            for k, prop in (("steps", core.N(1, 200, None, "Sampling steps.")), ("cfg", core.N(0, 30, None, "Prompt strength (CFG).", False)),
                            ("denoise", core.N(0, 1, None, "How much to change the input (1 = completely).", False)),
                            ("guidance", core.N(0, 30, None, "Flux guidance.", False)),
                            ("width", core.N(64, 8192, None, "Width in pixels.")), ("height", core.N(64, 8192, None, "Height in pixels.")),
                            ("batch_size", core.N(1, 16, None, "Images per run.")), ("length", core.N(1, 2000, None, "Frames.")),
                            ("sampler_name", core.T("Sampler.")), ("scheduler", core.T("Scheduler."))):
                if k in ins and not linked(ins[k]) and (k not in ("width", "height", "batch_size", "length") or "Latent" in ct or "Empty" in ct):
                    add(k, {**prop, "default": ins[k]}, (nid, k))
    return {"type": "object", "properties": props, "required": [], "x-fal-order-properties": order}, mapping


def fill(wf, body, put_file):
    """A copy of the workflow with the run's settings applied. Seeds left empty get a fresh random value."""
    wf, (sch, mapping) = copy.deepcopy(wf), parse(wf)
    for name, targets in mapping.items():
        if name not in body:
            if name.startswith("seed"):
                body = {**body, name: random.randint(0, 2 ** 48)}
            else:
                continue
        value = body[name]
        if (sch["properties"][name].get("_fal_ui_field")) and isinstance(value, str):
            value = put_file(value)
        for nid, inp in targets:
            wf[nid]["inputs"][inp] = value
    return wf


# ---------- running on a ComfyUI server ----------

def _upload(value):
    payload, mime, name = core.uri_bytes(value)
    ext = Path(name).suffix or ".png"
    data, ctype = core.multipart({"overwrite": "true"}, [("image", (f"muselight_{uuid.uuid4().hex[:10]}{ext}", payload, mime))])
    r = call(base() + "/upload/image", data=data, ctype=ctype, timeout=300)
    return f"{r['subfolder']}/{r['name']}" if r.get("subfolder") else r["name"]


def _errors(r):
    errs = r.get("node_errors") or {}
    parts = [f"{(e.get('class_type') or nid)}: {'; '.join(x.get('details') or x.get('message', '') for x in e.get('errors', []))}" for nid, e in errs.items()]
    return "; ".join(parts) or str(r.get("error", {}).get("message") or r.get("error") or r)


def run_workflow(wf, body, job):
    wf = fill(wf, body, _upload)
    try:
        r = call(base() + "/prompt", {"prompt": wf, "client_id": "muselight"})
    except RuntimeError as e:
        raise RuntimeError(f"ComfyUI rejected the workflow: {e}")
    if r.get("error") or not r.get("prompt_id"):
        raise RuntimeError("ComfyUI rejected the workflow: " + _errors(r))
    pid = r["prompt_id"]
    job["request_id"] = pid

    def check():
        h = call(f"{base()}/history/{pid}").get(pid)
        if not h:
            return None
        st = h.get("status") or {}
        if st.get("status_str") == "error":
            msg = next((m[1].get("exception_message") for m in st.get("messages", []) if m[0] == "execution_error"), "the workflow failed")
            raise RuntimeError(f"ComfyUI: {msg}")
        if not st.get("completed"):
            return None
        outs = []
        for node in h.get("outputs", {}).values():
            for files in node.values():
                for f in files if isinstance(files, list) else []:
                    if isinstance(f, dict) and f.get("filename") and f.get("type") == "output":
                        q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": "output"})
                        payload, kind = call(f"{base()}/view?{q}", raw=True, timeout=600)
                        outs.append(core.bytes_uri(payload, kind if kind != "application/octet-stream" else None))
        return {"prompt_id": pid, "outputs": len(outs)}, outs
    return core.wait(job, check, LABEL, cancel=lambda: call(base() + "/interrupt", data=b"", method="POST"), every=1.5)


# ---------- provider interface ----------

def models():
    return [{"id": name, "name": name, "cat": "your workflow", "desc": "Your ComfyUI workflow (runs on " + base() + ")"} for name in workflows()]


def schema(mid):
    wf = workflows().get(mid)
    if wf is None:
        raise RuntimeError(f"No ComfyUI workflow called '{mid}' in studio_data/comfy_workflows.")
    return parse(wf)[0]


def run(mid, body, job):
    wf = workflows().get(mid)
    if wf is None:
        raise RuntimeError(f"No ComfyUI workflow called '{mid}'.")
    return run_workflow(wf, body, job)


def test():
    s = call(base() + "/system_stats", timeout=10)
    dev = ((s.get("devices") or [{}])[0]).get("name", "")
    return f"Connected to ComfyUI {s.get('system', {}).get('comfyui_version', '')} {('· ' + dev) if dev else ''}".strip()
