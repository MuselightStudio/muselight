"""Alibaba Cloud Model Studio (DashScope): Wan video and images direct from Alibaba.
Its API address includes your workspace id, so it's saved alongside the key."""
from . import _core as core

ID, LABEL, GROUP = "dashscope", "Alibaba Model Studio (Wan)", "maker"
KEYS = ["DASHSCOPE_API_KEY"]
URLS = {"DASHSCOPE_URL": "https://YOUR-WORKSPACE-ID.ap-southeast-1.maas.aliyuncs.com"}
LINK, BILLING = "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key", "modelstudio.console.alibabacloud.com (Billing)"
HELP = ("Wan video and images direct from Alibaba. Save your API key, then your workspace address "
        "(https://<workspace id>.<region>.maas.aliyuncs.com, shown next to the key) below it.")
call = core.caller(__name__)
VIDEO_T = ["wan2.7-t2v", "wan2.6-t2v", "wan2.5-t2v-preview", "wan2.2-t2v-plus"]
VIDEO_I = ["wan2.7-i2v", "wan2.6-i2v", "wan2.6-i2v-flash", "wan2.5-i2v-preview", "wan2.2-i2v-flash", "wan2.2-i2v-plus"]
IMAGE = ["wan2.6-t2i", "wan2.5-t2i-preview"]


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0]), "X-DashScope-Async": "enable"}


def ready():
    return bool(core.key(KEYS[0])) and "YOUR-WORKSPACE" not in base()


def base():
    return (core.key("DASHSCOPE_URL") or URLS["DASHSCOPE_URL"]).rstrip("/")


def models():
    return ([{"id": m, "name": m, "cat": "text-to-video", "desc": "Wan, direct from Alibaba"} for m in VIDEO_T]
            + [{"id": m, "name": m, "cat": "image-to-video", "desc": "Wan, direct from Alibaba"} for m in VIDEO_I]
            + [{"id": m, "name": m, "cat": "text-to-image", "desc": "Wan, direct from Alibaba"} for m in IMAGE])


def schema(mid):
    new = mid.startswith("wan2.7")
    common = dict(prompt=core.T("What happens in the video."), negative_prompt=core.T("What to avoid."), audio_url=core.F("audio", "Optional sound track."),
                  duration=core.N(2, 15, 5, "Seconds (wan2.5: 5 or 10)."), prompt_extend=core.B(True, "Let an AI expand short prompts."),
                  seed=core.N(0, 2147483647), watermark=core.B(False))
    if "t2i" in mid:
        return core.S(prompt=core.T("What to make."), negative_prompt=core.T("What to avoid."), size=core.T("width*height", "1280*1280"),
                      n=core.N(1, 4, 1, "How many images."), prompt_extend=core.B(True), seed=core.N(0, 2147483647), watermark=core.B(False))
    size = (dict(resolution=core.E(["720P", "1080P"], "1080P"), ratio=core.E(["16:9", "9:16", "1:1", "4:3", "3:4"], "16:9")) if new
            else dict(resolution=core.E(["480P", "720P", "1080P"], None, "Image to video.")) if "i2v" in mid
            else dict(size=core.E(["1280*720", "720*1280", "1920*1080", "1080*1920", "960*960", "1440*1440"], None, "Text to video.")))
    if "i2v" in mid:
        return core.S(("prompt", "img_url"), img_url=core.F("image", "The first frame."), **common, **size,
                      **({} if new else {"shot_type": core.E(["single", "multi"], "single")}))
    return core.S(**common, **size, **({} if new else {"shot_type": core.E(["single", "multi"], "single")}))


def _task(path, payload, job, pick):
    d = core.unwrap(call(base() + path, payload))
    tid = (d.get("output") or {}).get("task_id")
    if not tid:
        raise RuntimeError(f"Alibaba: {d.get('message') or d}")
    job["request_id"] = tid

    def check():
        o = call(f"{base()}/api/v1/tasks/{tid}").get("output") or {}
        if o.get("task_status") == "SUCCEEDED":
            return o, pick(o)
        if o.get("task_status") in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(f"Alibaba: {o.get('message') or o.get('code') or o.get('task_status')}")
    return core.wait(job, check, LABEL, every=8)


def run(mid, body, job):
    inputs = {k: body.pop(k) for k in ("prompt", "negative_prompt", "img_url", "audio_url") if k in body}
    if "t2i" in mid:
        if mid.startswith("wan2.5"):
            return _task("/api/v1/services/aigc/text2image/image-synthesis", {"model": mid, "input": inputs, "parameters": body}, job,
                         lambda o: [r.get("url") for r in o.get("results", []) if r.get("url")])
        body["negative_prompt"] = inputs.get("negative_prompt", "")
        msg = {"role": "user", "content": [{"text": inputs.get("prompt", "")}]}
        return _task("/api/v1/services/aigc/image-generation/generation", {"model": mid, "input": {"messages": [msg]}, "parameters": body}, job,
                     lambda o: [c.get("image") for ch in o.get("choices", []) for c in (ch.get("message") or {}).get("content", []) if c.get("image")])
    return _task("/api/v1/services/aigc/video-generation/video-synthesis", {"model": mid, "input": inputs, "parameters": body}, job,
                 lambda o: [o["video_url"]] if o.get("video_url") else [])


def test():
    if not ready():
        raise RuntimeError("Save your workspace address too (https://<workspace id>.<region>.maas.aliyuncs.com).")
    try:
        call(f"{base()}/api/v1/tasks/key-check")
    except RuntimeError as e:
        if "didn't accept your key" in str(e):
            raise
    return "Connected to Alibaba Model Studio"
