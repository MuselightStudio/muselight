"""Kling AI's own API (global). It signs each request with your access key and secret key (a short-lived JWT)."""
import base64, hashlib, hmac, json, time
from . import _core as core

ID, LABEL, GROUP = "kling", "Kling AI", "maker"
KEYS = ["KLING_ACCESS_KEY", "KLING_SECRET_KEY"]
LINK, BILLING = "https://app.klingai.com/global/dev/api-key", "app.klingai.com/global/dev (Resource packs)"
HELP = "Kling video and images direct from Kuaishou. Save both the Access Key and the Secret Key."
API = "https://api-singapore.klingai.com"
call = core.caller(__name__)
# ponytail: Kling's model names are typed in (its docs aren't machine-readable); newer ones work by typing them in model_name
VIDEO_MODELS = ["kling-v2-6", "kling-v2-5-turbo", "kling-v2-1-master", "kling-v2-1", "kling-v1-6"]
VIDEO = core.S(prompt=core.T("What happens in the video."), negative_prompt=core.T("What to avoid."),
               model_name=core.T("Kling model, e.g. " + ", ".join(VIDEO_MODELS), VIDEO_MODELS[0]),
               image=core.F("image", "First frame (makes it image to video)."), image_tail=core.F("image", "Last frame (image to video)."),
               mode=core.E(["std", "pro"], "std", "pro = higher quality, costs more."), duration=core.E(["5", "10"], "5", "Seconds."),
               aspect_ratio=core.E(["16:9", "9:16", "1:1"], "16:9", "Text to video only."), cfg_scale=core.N(0, 1, None, "Prompt strength.", False))
IMAGE = core.S(prompt=core.T("What to make."), negative_prompt=core.T("What to avoid."), model_name=core.T("Kling image model.", "kling-v2"),
               image=core.F("image", "Optional reference image."), n=core.N(1, 9, 1), aspect_ratio=core.E(["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"], "1:1"))


def _jwt():
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
    now = int(time.time())
    head, claims = b64(b'{"alg":"HS256","typ":"JWT"}'), b64(json.dumps({"iss": core.key(KEYS[0]), "exp": now + 1800, "nbf": now - 5}).encode())
    sig = b64(hmac.new(core.key(KEYS[1]).encode(), head + b"." + claims, hashlib.sha256).digest())
    return (head + b"." + claims + b"." + sig).decode()


def headers():
    return {"Authorization": "Bearer " + _jwt()}


def models():
    return [{"id": "video", "name": "Kling video", "cat": "video", "desc": "Text or image to video. Pick the Kling version under model_name."},
            {"id": "image", "name": "Kling image", "cat": "image", "desc": "Kling image generation."}]


def schema(mid):
    return IMAGE if mid == "image" else VIDEO


def _plain(v):
    return v.split(",", 1)[1] if isinstance(v, str) and v.startswith("data:") else v  # Kling takes links or bare base64


def run(mid, body, job):
    body = {k: _plain(v) for k, v in body.items()}
    path = "/v1/images/generations" if mid == "image" else "/v1/videos/image2video" if body.get("image") else "/v1/videos/text2video"
    if path.endswith("image2video"):
        body.pop("aspect_ratio", None)
    d = core.unwrap(call(API + path, body))
    tid = d["task_id"]
    job["request_id"] = tid

    def check():
        r = core.unwrap(call(f"{API}{path}/{tid}"))
        if r.get("task_status") == "succeed":
            return r, core.media_urls(r.get("task_result"), "task_result")
        if r.get("task_status") == "failed":
            raise RuntimeError(f"Kling: {r.get('task_status_msg') or 'the task failed'}")
    return core.wait(job, check, LABEL, every=5)


def test():
    try:
        call(f"{API}/v1/videos/text2video/key-check")
    except RuntimeError as e:
        if "didn't accept your key" in str(e):
            raise
    return "Connected to Kling AI"
