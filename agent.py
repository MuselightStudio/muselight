"""Optional AI assistants for Muselight: ChatGPT, Claude, Grok, Venice and OpenClaw.

Each chat runs a tool loop in a background thread. The assistant can search models, read their
inputs, start generations and workflows, wait for results and look at the images. Anything that
spends credits waits for the user's approval unless the chat is set to auto-run.

Keys come from environment variables (never stored by the app):
  OPENAI_API_KEY, ANTHROPIC_API_KEY, XAI_API_KEY, VENICE_API_KEY,
  OPENCLAW_GATEWAY_TOKEN (+ OPENCLAW_URL, default http://127.0.0.1:18789)
"""
import base64, io, json, os, threading, time, urllib.error, urllib.request, uuid
from pathlib import Path

PROVIDERS = {
    # free
    "openrouter": {"name": "OpenRouter · free models", "env": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1",
                   "hint": "Free: make an account at openrouter.ai and create a key (no card needed), then paste it below. Free models allow about 50 requests a day (1,000 after a one-time $10 top-up); one task often uses 5–10."},
    "ollama": {"name": "Ollama · local, free", "local": "OLLAMA_URL", "url": "http://127.0.0.1:11434",
               "hint": "Free and private: install Ollama from ollama.com, run <code>ollama pull qwen3</code> (or any model with tool support) and keep Ollama open. Needs a decent graphics card."},
    "lmstudio": {"name": "LM Studio · local, free", "local": "LMSTUDIO_URL", "url": "http://127.0.0.1:1234",
                 "hint": "Free and private: install LM Studio, download a model with tool-use support, then start its local server (Developer tab → Start Server)."},
    # your own API key
    "claude": {"name": "Claude · API key", "env": "ANTHROPIC_API_KEY", "default": "claude-opus-5-5"},
    "chatgpt": {"name": "ChatGPT · API key", "env": "OPENAI_API_KEY", "base": "https://api.openai.com/v1", "prefer": "gpt"},
    "grok": {"name": "Grok · API key", "env": "XAI_API_KEY", "base": "https://api.x.ai/v1", "prefer": "grok"},
    "venice": {"name": "Venice · API key", "env": "VENICE_API_KEY", "base": "https://api.venice.ai/api/v1", "prefer": ""},
    "openclaw": {"name": "OpenClaw gateway", "env": "OPENCLAW_GATEWAY_TOKEN", "default": "openclaw:main"},
    # cheap pay-per-use hosts of open models (their keys also run image/video models)
    "deepinfra": {"name": "DeepInfra · API key", "env": "DEEPINFRA_API_KEY", "base": "https://api.deepinfra.com/v1/openai", "prefer": "qwen"},
    "together": {"name": "Together AI · API key", "env": "TOGETHER_API_KEY", "base": "https://api.together.xyz/v1", "prefer": "qwen"},
    "siliconflow": {"name": "SiliconFlow · API key", "env": "SILICONFLOW_API_KEY", "base": "https://api.siliconflow.com/v1", "prefer": "qwen"},
    "novita": {"name": "Novita AI · API key", "env": "NOVITA_API_KEY", "base": "https://api.novita.ai/openai", "prefer": "qwen"},
    # a model you host yourself on a RunPod GPU (GPUs → Assistant model)
    "runpod": {"name": "RunPod · your own model", "env": "RUNPOD_LLM_ENDPOINT",
               "hint": "Your own private model on a RunPod GPU that costs nothing while idle: open GPUs → Assistant model → Deploy. "
                       "The first message after a break waits a minute or two while the GPU starts."},
}
# Claude models that accept server-side refusal fallbacks ("default" routing by refusal category)
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
MAX_STEPS = 40  # model calls per user message

SYSTEM = """You are the assistant inside Muselight, a desktop app for generating images, video and audio with AI models.
Every run uses the user's own provider accounts, paid from each provider's own balance. Models come from fal (plain ids like fal-ai/flux/dev) and, when the user has added their keys, about 25 other providers whose ids carry a prefix: wavespeed, atlas, replicate, runware, kie, piapi, segmind, deepinfra, together, siliconflow, huggingface, google, openai, xai, bfl, byteplus, dashscope, kling, minimax, luma, runway, ideogram, recraft, stability, runpod, comfyui (e.g. runware:bfl-flux-1-schnell, runpod:wan-2-5, comfyui:<the user's workflow>). The same model is often on several providers at different prices; many descriptions start with the price. comfyui: models are the user's own ComfyUI workflows (free, on their GPU); runpod:<endpoint>/<workflow> runs them on the user's RunPod GPU.
With 'Cheapest' on (the default), the app runs each model on the cheapest connected provider that has the same model, translating the settings, so you can pick any provider's id; a run's results say which provider it used and whether an unconnected provider lists a lower price.
You can do things for the user with your tools, or explain how to do them in the app. Be brief and concrete.

How the app works (for when the user wants to do it themselves):
- Create tab: search a model, fill in its settings, press Run. 'Copies' repeats it; 'A list (one per line)' makes one version per line ({{line}} in any box).
- Workflows tab + visual editor: chain models; input nodes for prompts, batch prompts, images, videos and any parameter.
- Batch tab: switch any setting to Batch and give values separated by a line containing only ---.
- Compare tab: one set of inputs sent to several models, translated to each model's own format.
- Automations: watch a folder and run a saved workflow on every image dropped in.
- Results tab: filters, grouping, Cards / Gallery / List views, stars (Create also shows the latest results beside the settings). 'Files' opens the output folder; 'Connections' holds the provider and assistant keys.

Working rules:
- Before generating with a model, call get_model_inputs so you use its real setting names and allowed values.
- Local files are written as @path, e.g. @uploads/hero.png or @outputs/2026-10-20/x.jpg. Images the user attaches arrive as @uploads/... paths.
- In a prompt, @name refers to an uploaded file by name (@hero = uploads/hero.png). The app adds that file to the model's inputs and rewrites the mention the way the model expects, so write e.g. "put @hero in the style of @poster" rather than numbering images yourself.
- Every generation spends the user's credits with the provider it runs on. Keep counts to what was asked. The app may ask the user to approve a run; if they decline, don't retry it unasked.
- After starting runs, use wait_for_runs, then view_image to check results when quality matters, and report what you made with the file paths.
- Never claim a run worked without checking its result."""

TOOLS = [
    {"name": "search_models", "description": "Search the models the user can run, by words in their name, id or type. One result per model (the app runs it on the cheapest connected provider), newest first, with a list price when known.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]}},
    {"name": "get_model_inputs", "description": "List a model's input settings: names, types, allowed values, defaults and which are required.",
     "parameters": {"type": "object", "properties": {"model": {"type": "string", "description": "model id, e.g. krea/v3/edit or runware:bfl-flux-1-schnell"}}, "required": ["model"]}},
    {"name": "generate", "description": "Start generations (spends credits). Runs `count` times with the same inputs; leave seed out for variety. Returns run ids.",
     "parameters": {"type": "object", "properties": {
         "model": {"type": "string"}, "inputs": {"type": "object", "description": "Setting name -> value. Files as @path or URLs."},
         "count": {"type": "integer", "default": 1}, "label": {"type": "string", "description": "Short name shown in Results"}},
         "required": ["model", "inputs"]}},
    {"name": "list_workflows", "description": "List the user's saved workflows.", "parameters": {"type": "object", "properties": {}}},
    {"name": "run_workflow", "description": "Run a saved workflow (spends credits). `rows` fills {{name}} placeholders; each row is one run.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "rows": {"type": "array", "items": {"type": "object"}}}, "required": ["name"]}},
    {"name": "get_results", "description": "Recent runs with status, model, prompt, output files and errors. Pass run_ids to look at specific runs.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "default": 10}, "run_ids": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "wait_for_runs", "description": "Wait until the given runs finish (up to timeout_seconds, max 900), then return their results.",
     "parameters": {"type": "object", "properties": {"run_ids": {"type": "array", "items": {"type": "string"}}, "timeout_seconds": {"type": "integer", "default": 600}}, "required": ["run_ids"]}},
    {"name": "view_image", "description": "Look at an image file (an output or upload) to judge it. Pass its @path.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "list_files", "description": "List the user's uploaded reference files, or recent outputs.",
     "parameters": {"type": "object", "properties": {"folder": {"type": "string", "enum": ["uploads", "outputs"]}, "limit": {"type": "integer", "default": 30}}, "required": ["folder"]}},
]
SPENDS = {"generate", "run_workflow"}

chats = {}  # chat id -> Chat


def data_dir(root):
    """studio_data next to the program (portable); AppData when that folder is read-only, e.g. Program Files."""
    d = Path(root) / "studio_data"
    try:
        d.mkdir(exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return d
    except OSError:
        d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Fal Studio" / "studio_data"  # old name kept: data saved before the rename
        d.mkdir(parents=True, exist_ok=True)
        return d
studio = None  # the studio module, set by init()


def init(module):
    global studio
    studio = module


def _local_url(pid):
    return os.environ.get(PROVIDERS[pid]["local"], PROVIDERS[pid]["url"]).rstrip("/")


def _running(pid):
    try:
        urllib.request.urlopen(_local_url(pid) + "/v1/models", timeout=0.8).close()
        return True
    except Exception:
        return False


def provider_status():
    out = []
    for pid, p in PROVIDERS.items():
        if p.get("local"):
            ready = _running(pid)
        else:
            ready = bool(os.environ.get(p["env"])) or (pid == "openclaw" and bool(os.environ.get("OPENCLAW_GATEWAY_PASSWORD")))
            ready = ready and (pid != "runpod" or bool(os.environ.get("RUNPOD_API_KEY")))
        hint = p.get("hint") or (f"Needs your own {p['name'].split(' ·')[0]} API key. Paste it below."
                                 if pid != "openclaw" else "Turn on the gateway's chat completions endpoint, then enter its address and token below.")
        out.append({"id": pid, "name": p["name"], "key_set": ready, "local": bool(p.get("local")), "hint": hint, "default": p.get("default", "")})
    return out


def _http(url, body=None, headers=None, timeout=300):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read().decode(errors='replace')[:600]}")


def _openai_target(pid):
    if PROVIDERS[pid].get("local"):
        return _local_url(pid) + "/v1", {}
    if pid == "openrouter":
        return PROVIDERS[pid]["base"], {"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}", "X-Title": "Muselight"}
    if pid == "openclaw":
        base = os.environ.get("OPENCLAW_URL", "http://127.0.0.1:18789").rstrip("/") + "/v1"
        key = os.environ.get("OPENCLAW_GATEWAY_TOKEN") or os.environ.get("OPENCLAW_GATEWAY_PASSWORD", "")
    elif pid == "runpod":  # a vLLM endpoint answers OpenAI-style requests under /openai/v1
        base = f"https://api.runpod.ai/v2/{os.environ.get('RUNPOD_LLM_ENDPOINT', '')}/openai/v1"
        key = os.environ.get("RUNPOD_API_KEY", "")
    else:
        base, key = PROVIDERS[pid]["base"], os.environ.get(PROVIDERS[pid]["env"], "")
    return base, {"Authorization": f"Bearer {key}"}


def list_models(pid):
    if pid == "claude":
        import anthropic
        ids = [m.id for m in anthropic.Anthropic().models.list()]
    elif pid == "runpod":  # the endpoint's own model (asking the endpoint would wake a GPU just to list it)
        import providers
        ep = next((e for e in providers.runpod.my_endpoints() if e["id"] == os.environ.get("RUNPOD_LLM_ENDPOINT")), None)
        if not ep:
            raise RuntimeError("That RunPod endpoint no longer exists. Deploy one under GPUs → Assistant model.")
        ids = [ep.get("model") or "default"]
    else:
        base, headers = _openai_target(pid)
        data = _http(base + "/models", headers=headers, timeout=30)
        items = sorted(data.get("data", []), key=lambda m: -(m.get("created") or 0))
        if pid == "openrouter":  # the assistant needs tool calling; free models first
            items = [m for m in items if "tools" in (m.get("supported_parameters") or [])]
            free = lambda m: m["id"].endswith(":free") or (m.get("pricing", {}).get("prompt") == "0" and m.get("pricing", {}).get("completion") == "0")
            items = [m for m in items if free(m)] + [m for m in items if not free(m)]
        ids = [m["id"] for m in items]
        prefer = PROVIDERS[pid].get("prefer")
        if prefer:
            ids = [i for i in ids if prefer in i.lower()] + [i for i in ids if prefer not in i.lower()]
    default = PROVIDERS[pid].get("default")
    if default and default in ids:
        ids.remove(default)
    return ([default] if default else []) + ids


# ---------- images ----------

def _image_b64(path, max_side=1568):
    """Read an @path image, shrink it so it is cheap to send, return (media_type, base64)."""
    p = Path(path[1:] if path.startswith("@") else path)
    p = p if p.is_absolute() else studio.DATA / p
    if not p.is_file():
        raise RuntimeError(f"No file at {path}")
    try:
        from PIL import Image
        im = Image.open(p)
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=88)
        return "image/jpeg", base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        import mimetypes
        return mimetypes.guess_type(p)[0] or "image/png", base64.b64encode(p.read_bytes()).decode()


# ---------- tools ----------

def _summary(j):
    inp = j["steps"][0]["inputs"]
    prompt = studio.fill(inp.get("prompt") or inp.get("text") or "", j.get("vars") or {})
    dur = round(j["finished"] - j["started"]) if j.get("finished") and j.get("started") else None
    return {"run_id": j["id"], "status": j["status"], "model": " -> ".join(s["model"] for s in j["steps"]),
            "prompt": str(prompt)[:300], "files": ["@" + f for r in j["results"] for f in r["files"]],
            "seconds": dur, "error": j.get("error")}


def run_tool(chat, name, args):
    if name == "search_models":
        words = str(args.get("query", "")).lower().split()
        hits, seen = [], set()
        for m in sorted(studio.get_models(), key=lambda m: m.get("date", ""), reverse=True):
            if m["key"] not in seen and all(w in f"{m['id']} {m['name']} {m['cat']}".lower() for w in words):
                seen.add(m["key"])
                cost = m.get("cost")
                hits.append({"id": m["id"], "name": m["name"], "category": m["cat"], "description": (m.get("desc") or "")[:160],
                             **({"list_price": f"${cost['usd']:g} per {cost['per']}"} if cost else {})})
        return hits[: int(args.get("limit") or 10)]
    if name == "get_model_inputs":
        sch = studio.get_schema(args["model"])
        req = set(sch.get("required") or [])
        out = {}
        for k, p in (sch.get("properties") or {}).items():
            opts = [p] + p.get("anyOf", [])
            enum = [v for o in opts for v in o.get("enum", [])]
            out[k] = {"type": [o.get("type") for o in opts if o.get("type")] or None, "required": k in req,
                      "default": p.get("default"), "allowed": enum or None, "max_items": p.get("maxItems"),
                      "description": (p.get("description") or "")[:200]}
        return out
    if name == "list_workflows":
        return sorted(p.stem for p in studio.WORKFLOWS.glob("*.json"))
    if name == "list_files":
        folder = studio.DATA / ("uploads" if args.get("folder") == "uploads" else "outputs")
        files = sorted((f for f in folder.rglob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
        return ["@" + f.relative_to(studio.DATA).as_posix() for f in files[: int(args.get("limit") or 30)]]
    if name in ("generate", "run_workflow"):
        if not chat.approve(name, args):
            return {"declined": True, "message": "The user declined this run. Do not retry it unless they ask."}
        if name == "generate":
            count = max(1, min(int(args.get("count") or 1), 50))
            ids = studio.submit(args.get("label") or f"assistant · {args['model']}", [{"model": args["model"], "inputs": args["inputs"]}], [{}], count, origin="assistant")
        else:
            wf = studio.load_workflow(args["name"])
            ids = studio.submit(f"assistant · {args['name']}", wf["steps"], args.get("rows") or [{}], 1, wf.get("values"), origin="assistant")
        chat.run_ids.extend(ids)
        return {"run_ids": ids, "message": f"Started {len(ids)} run(s). Use wait_for_runs to get the results."}
    if name == "get_results":
        ids = args.get("run_ids")
        js = [studio.jobs[i] for i in ids if i in studio.jobs] if ids else sorted(studio.jobs.values(), key=lambda j: -j["created"])[: int(args.get("limit") or 10)]
        return [_summary(j) for j in js]
    if name == "wait_for_runs":
        ids = [i for i in args.get("run_ids", []) if i in studio.jobs]
        end = time.time() + min(int(args.get("timeout_seconds") or 600), 900)
        while time.time() < end and not chat.stop and any(studio.jobs[i]["status"] in ("queued", "running") for i in ids):
            time.sleep(2)
        return [_summary(studio.jobs[i]) for i in ids]
    if name == "view_image":
        return {"image": args["path"]}  # the provider adapter turns this into a real image for the model
    raise RuntimeError(f"Unknown tool {name}")


# ---------- chat ----------

class Chat:
    def __init__(self, provider, model, auto):
        self.id, self.provider, self.model, self.auto = uuid.uuid4().hex, provider, model, bool(auto)
        self.log, self.history, self.run_ids = [], [], []
        self.busy, self.stop = False, False
        self.pending = {}  # approval id -> {"event", "ok"}
        self.lock = threading.Lock()

    def add(self, kind, **kw):
        entry = {"id": uuid.uuid4().hex[:10], "kind": kind, "t": time.time(), **kw}
        with self.lock:
            self.log.append(entry)
        return entry

    def approve(self, tool, args):
        if self.auto:
            return True
        n = (max(1, int(args.get("count") or 1)) if tool == "generate" else len(args.get("rows") or [{}]))
        what = f"{n} run{'s' if n != 1 else ''} of {args.get('model') or 'workflow ' + str(args.get('name'))}"
        entry = self.add("approval", tool=tool, summary=what, args=args, status="pending")
        ev = threading.Event()
        self.pending[entry["id"]] = {"event": ev, "ok": False}
        while not ev.wait(1):
            if self.stop:
                entry["status"] = "cancelled"
                return False
        ok = self.pending.pop(entry["id"])["ok"]
        entry["status"] = "approved" if ok else "declined"
        return ok

    def answer(self, approval_id, ok):
        p = self.pending.get(approval_id)
        if p:
            p["ok"] = ok
            p["event"].set()

    def view(self):
        with self.lock:
            return {"id": self.id, "provider": self.provider, "model": self.model, "auto": self.auto, "busy": self.busy,
                    "log": [{k: v for k, v in e.items() if k != "args"} | ({"args": e["args"]} if e["kind"] == "approval" else {}) for e in self.log]}

    def send(self, text, images):
        self.add("user", text=text, images=images)
        self.busy, self.stop = True, False
        threading.Thread(target=self._run, args=(text, images), daemon=True).start()

    def _run(self, text, images):
        try:
            (self._claude if self.provider == "claude" else self._openai)(text, images)
        except Exception as e:
            self.add("error", text=str(e))
        finally:
            self.busy = False

    def _tool(self, name, args):
        label = {"search_models": f"Searching models for “{args.get('query', '')}”", "get_model_inputs": f"Reading the settings of {args.get('model')}",
                 "generate": f"Generating with {args.get('model')}", "run_workflow": f"Running workflow {args.get('name')}",
                 "wait_for_runs": "Waiting for results", "view_image": f"Looking at {args.get('path')}", "get_results": "Checking results",
                 "list_workflows": "Listing workflows", "list_files": f"Listing {args.get('folder')}"}.get(name, name)
        entry = self.add("tool", name=name, label=label, status="running")
        try:
            result = run_tool(self, name, args)
            entry["status"] = "declined" if isinstance(result, dict) and result.get("declined") else "done"
            if name in ("wait_for_runs", "get_results"):
                entry["files"] = [f for r in result for f in r["files"]][:12]
            if name == "view_image":
                entry["files"] = [args.get("path")]
            return result, False
        except Exception as e:
            entry.update(status="error", error=str(e))
            return {"error": str(e)}, True

    # --- Claude (official Anthropic SDK, manual tool loop so runs can wait for approval) ---
    def _claude(self, text, images):
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or None)
        content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": d}} for mt, d in map(_image_b64, images)]
        self.history.append({"role": "user", "content": content + [{"type": "text", "text": text}]})
        tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in TOOLS]
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if self.model in FALLBACK_MODELS else {}
        for _ in range(MAX_STEPS):
            if self.stop:
                return self.add("note", text="Stopped.")
            resp = client.beta.messages.create(model=self.model, max_tokens=16000, system=SYSTEM, tools=tools,
                                               messages=self.history, output_config={"effort": "medium"}, **extra)
            self.history.append({"role": "assistant", "content": resp.content})  # whole content, unchanged (append-only)
            said = "".join(b.text for b in resp.content if b.type == "text").strip()
            if said:
                self.add("assistant", text=said)
            if resp.stop_reason == "refusal":
                return self.add("error", text="Claude declined this request.")
            if resp.stop_reason == "pause_turn":
                continue
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                return
            results = []
            for b in uses:
                out, err = self._tool(b.name, b.input)
                if b.name == "view_image" and not err:
                    try:
                        mt, d = _image_b64(b.input["path"])
                        block = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": d}}]
                    except Exception as e:
                        block, err = str(e), True
                else:
                    block = json.dumps(out, default=str)[:60000]
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": block, **({"is_error": True} if err else {})})
            self.history.append({"role": "user", "content": results})
        self.add("note", text="Reached the step limit for one message. Say “continue” to keep going.")

    # --- ChatGPT, Grok, Venice, OpenClaw (OpenAI-compatible chat completions) ---
    def _openai(self, text, images):
        base, headers = _openai_target(self.provider)
        if not self.history:
            self.history.append({"role": "system", "content": SYSTEM})
        parts = [{"type": "image_url", "image_url": {"url": f"data:{mt};base64,{d}"}} for mt, d in map(_image_b64, images)]
        self.history.append({"role": "user", "content": parts + [{"type": "text", "text": text}] if parts else text})
        tools = [{"type": "function", "function": t} for t in TOOLS]
        for _ in range(MAX_STEPS):
            if self.stop:
                return self.add("note", text="Stopped.")
            resp = _http(base + "/chat/completions", {"model": self.model, "messages": self.history, "tools": tools}, headers)
            msg = resp["choices"][0]["message"]
            keep = {k: msg[k] for k in ("role", "content", "tool_calls") if msg.get(k) is not None}
            self.history.append(keep)
            if (msg.get("content") or "").strip():
                self.add("assistant", text=msg["content"].strip())
            calls = msg.get("tool_calls") or []
            if not calls:
                return
            seen_images = []
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args, out, err = {}, {"error": "Arguments were not valid JSON"}, True
                else:
                    out, err = self._tool(c["function"]["name"], args)
                if c["function"]["name"] == "view_image" and not err:
                    seen_images.append(args["path"])
                    out = {"message": "The image follows in the next message."}
                self.history.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, default=str)[:60000]})
            if seen_images:  # tool messages can't carry images here, so show them as a follow-up
                parts = [{"type": "image_url", "image_url": {"url": f"data:{mt};base64,{d}"}} for mt, d in map(_image_b64, seen_images)]
                self.history.append({"role": "user", "content": parts + [{"type": "text", "text": "Images requested with view_image: " + ", ".join(seen_images)}]})
        self.add("note", text="Reached the step limit for one message. Say “continue” to keep going.")


def complete(provider, model, system, prompt, images=()):
    """One answer from the user's assistant, no tools (Storyboard scenes, Marketing concepts, hook scores of @path images)."""
    keyed = [pid for pid, p in PROVIDERS.items() if not p.get("local") and os.environ.get(p["env"]) and (pid != "runpod" or os.environ.get("RUNPOD_API_KEY"))]
    if provider not in keyed:  # local apps (Ollama, LM Studio) are only checked when nothing online is set up: each check takes a moment
        ready = keyed or [p["id"] for p in provider_status() if p["key_set"]]
        provider = provider if provider in ready else (ready[0] if ready else None)
    if not provider:
        raise RuntimeError("This needs an AI assistant. Set one up under ✦ Assistant (a free OpenRouter key works).")
    model = model or list_models(provider)[0]
    if provider == "claude":
        import anthropic
        content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": d}} for mt, d in map(_image_b64, images)] + [{"type": "text", "text": prompt}]
        r = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or None).messages.create(
            model=model, max_tokens=8000, system=system, messages=[{"role": "user", "content": content}])
        return "".join(b.text for b in r.content if b.type == "text")
    base, headers = _openai_target(provider)
    parts = [{"type": "image_url", "image_url": {"url": f"data:{mt};base64,{d}"}} for mt, d in map(_image_b64, images)]
    user = parts + [{"type": "text", "text": prompt}] if parts else prompt
    r = _http(base + "/chat/completions", {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, headers)
    return r["choices"][0]["message"].get("content") or ""


_connector = None


def connector_call(name, args):
    """Tool calls from outside apps (the MCP connector). Those apps ask their user before each call, so runs aren't gated here."""
    global _connector
    if _connector is None:
        _connector = Chat("connector", "", auto=True)
    if name == "view_image":
        mt, data = _image_b64(args["path"])
        return {"media_type": mt, "data": data}
    return run_tool(_connector, name, args)


def new_chat(provider, model, auto):
    if provider not in PROVIDERS:
        raise RuntimeError("Unknown assistant")
    c = Chat(provider, model or PROVIDERS[provider].get("default") or "", auto)
    chats[c.id] = c
    return c


def selftest():
    """Drives the OpenAI-style loop with a scripted model: search, read inputs, approve a run (not submitted), reply."""
    import types
    calls = []
    script = iter([
        {"tool_calls": [{"id": "1", "function": {"name": "search_models", "arguments": json.dumps({"query": "krea edit", "limit": 2})}}]},
        {"tool_calls": [{"id": "2", "function": {"name": "generate", "arguments": json.dumps({"model": "krea/v3/edit", "inputs": {"prompt": "x"}, "count": 2})}}]},
        {"content": "Done."},
    ])
    global _http
    real = _http
    _http = lambda url, body=None, headers=None, timeout=300: (calls.append(body), {"choices": [{"message": {"role": "assistant", **next(script)}}]})[1]
    fake_studio = types.SimpleNamespace(get_models=lambda: [{"id": "krea/v3/edit", "name": "Krea 3 Edit", "cat": "image-to-image", "desc": "", "date": "1", "key": "edit krea 3 ~image"}],
                                        submit=lambda *a: (_ for _ in ()).throw(AssertionError("must not submit when declined")))
    global studio
    old, studio = studio, fake_studio
    try:
        os.environ.setdefault("VENICE_API_KEY", "test")
        c = Chat("venice", "test-model", auto=False)
        c.send("make two images", [])
        for _ in range(50):
            ap = [e for e in c.log if e["kind"] == "approval" and e["status"] == "pending"]
            if ap:
                assert ap[0]["summary"] == "2 runs of krea/v3/edit", ap[0]["summary"]
                c.answer(ap[0]["id"], False)
                break
            time.sleep(0.05)
        while c.busy:
            time.sleep(0.05)
        kinds = [e["kind"] for e in c.log]
        assert kinds == ["user", "tool", "tool", "approval", "assistant"], kinds
        assert c.log[1]["status"] == "done" and c.log[2]["status"] == "declined" and c.log[3]["status"] == "declined"
        tool_msgs = [m for m in c.history if m.get("role") == "tool"]
        assert json.loads(tool_msgs[0]["content"])[0]["id"] == "krea/v3/edit"
        assert json.loads(tool_msgs[1]["content"])["declined"] is True
        assert calls[0]["tools"][0]["type"] == "function" and calls[0]["messages"][0]["role"] == "system"
    finally:
        _http, studio = real, old
    print("agent selftest ok")
