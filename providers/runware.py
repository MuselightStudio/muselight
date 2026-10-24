"""Runware: hundreds of models through one endpoint, each with a published settings schema."""
import json, urllib.request, uuid
from . import _core as core

ID, LABEL, GROUP = "runware", "Runware", "market"
KEYS = ["RUNWARE_API_KEY"]
LINK, BILLING = "https://my.runware.ai/keys", "my.runware.ai/wallet"
HELP = "Usually the cheapest per image, with fast open models plus Kling, Veo, Seedance, MiniMax and more."
API, INDEX = "https://api.runware.ai/v1", "https://runware.ai/docs/models/index.json"
call = core.caller(__name__)
info = {}  # model id -> {schema, task, air, paths: field -> ("inputs"|"settings"|"", key)}
PLUMBING = {"model", "taskType", "taskUUID", "webhookURL", "includeCost", "routing", "uploadEndpoint", "ttl", "outputType", "deliveryMethod", "safety"}


def headers():
    return {"Authorization": "Bearer " + core.key(KEYS[0])}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": core.UA}), timeout=60) as r:
        return json.load(r)


def models():
    out = []
    for m in _get(INDEX):
        caps = [c for c in m.get("capabilities", []) if c != "checkpoint"]
        if m.get("status") != "live" or not any(c.split("-")[-1] in ("image", "video", "audio", "edit", "upscale", "3d") or c == "edit" for c in caps):
            continue
        out.append({"id": m["id"], "name": m.get("name") or m["id"], "cat": caps[0] if caps else "", "desc": ", ".join(caps), "air": m.get("air")})
        info.setdefault(m["id"], {})["url"] = m.get("schema")
    return out


def schema(mid):
    entry = info.setdefault(mid, {})
    if "schema" not in entry:
        doc = _get(entry.get("url") or f"https://runware.ai/docs/models/{mid}/schema.json")
        task = doc["components"]["schemas"]["RequestBody"]["items"]
        props, paths, req = {}, {}, set(task.get("required") or [])
        for k, p in (task.get("properties") or {}).items():
            if k in PLUMBING:
                continue
            if k in ("inputs", "settings") and p.get("type") == "object":
                for sk, sp in (p.get("properties") or {}).items():
                    name = sk if sk not in props and sk not in task["properties"] else f"{k}_{sk}"
                    props[name], paths[name] = sp, (k, sk)
                    if sk in (p.get("required") or []):
                        req.add(name)
                continue
            props[k], paths[k] = p, ("", k)
        pricing = (doc["info"].get("x-pricing") or {}).get("rates") or []
        sch = core.normalize({"type": "object", "properties": props, "required": [r for r in req if r in props]}, list(props))
        sch["description"] = "; ".join(r.get("display", "") for r in pricing[:3])
        entry.update(rates=pricing, measured=(doc["info"].get("x-pricing") or {}).get("measured"))
        entry.update(schema=sch, paths=paths, air=doc["info"]["x-air-id"], task=(task["properties"].get("taskType") or {}).get("const", "imageInference"))
    return entry["schema"]


def cost(mid):
    """This model's price from its rate card (first rate), or the measured 1024×1024 price for image models."""
    schema(mid)
    rates, measured = info[mid].get("rates") or [], info[mid].get("measured") or []
    unit = {"durationSecond": "second", "image": "image", "outputImage": "image", "megapixel": "megapixel", "request": "run"}
    for r in rates:
        if not r.get("after") and r.get("unit") in unit:
            return core.cost(r.get("amount"), unit[r["unit"]])
    m = next((x for x in measured if "1024" in str(x.get("configuration"))), measured[0] if measured else None)
    return core.cost(m.get("price"), "image") if m else None


def quote(mid, body):
    """The price from Runware's rate card for these settings: the rate for the chosen resolution times the seconds or images.
    None for models billed by GPU time (their price is only known after the run)."""
    schema(mid)
    rates = [r for r in info[mid].get("rates") or [] if r.get("amount") is not None]
    if not rates:
        return None
    n = int(body.get("numberResults") or 1)
    secs = float(body.get("duration") or (schema(mid)["properties"].get("duration") or {}).get("default") or 5)
    want = str(body.get("resolution") or "").lower()
    if not want and body.get("height") and body.get("width"):
        want = f"{min(int(body['height']), int(body['width']))}p"

    def pick(unit):
        rs = [r for r in rates if r.get("unit") == unit and not r.get("after") and "upload" not in str(r.get("label", "")).lower()]
        if not rs:
            return None
        exact = [r for r in rs if str(r.get("label", "")).lower() == want]
        if exact or not want:
            return (exact or rs)[0]
        num = lambda s: float(core.re.sub(r"[^0-9.]", "", s.lower().replace("k", "000")) or 0)
        return min(rs, key=lambda r: abs(num(str(r.get("label", ""))) - num(want)))
    total, found = 0.0, False
    for unit, qty in (("durationSecond", secs * n), ("image", n), ("outputImage", n), ("request", n)):
        r = pick(unit)
        if r:
            total, found = total + r["amount"] * qty, True
    extra = [r for r in rates if r.get("after") and r.get("unit") == "inputImage"]
    refs = sum(len(v) for v in body.values() if isinstance(v, list) and all(isinstance(x, str) for x in v))
    for r in extra:
        total += r["amount"] * max(0, refs - int(r["after"]))
    return total if found else None


def charged(result):
    return sum(i.get("cost") or 0 for i in (result.get("data") or []) if isinstance(i, dict)) or None


def run(mid, body, job):
    schema(mid)
    e = info[mid]
    task = {"taskType": e["task"], "taskUUID": str(uuid.uuid4()), "model": e["air"], "deliveryMethod": "async", "includeCost": True}
    if e["task"] == "imageInference":
        task["outputType"] = "URL"
    for k, v in body.items():
        group, key = e["paths"].get(k, ("", k))
        (task.setdefault(group, {}) if group else task)[key] = v
    r = call(API, [task])
    if r.get("errors"):
        raise RuntimeError("Runware: " + "; ".join(x.get("message", "") for x in r["errors"]))
    job["request_id"] = task["taskUUID"]

    def check():
        res = call(API, [{"taskType": "getResponse", "taskUUID": task["taskUUID"]}])
        if res.get("errors"):
            raise RuntimeError("Runware: " + "; ".join(x.get("message", "") for x in res["errors"]))
        items = res.get("data") or []
        if items and all(i.get("status", "success") == "success" for i in items):
            return res, [u for i in items for u in core.media_urls({k: v for k, v in i.items() if k.lower().endswith("url")})]
        bad = [i for i in items if i.get("status") == "error"]
        if bad:
            raise RuntimeError("Runware: " + str(bad[0].get("error") or bad[0]))
    return core.wait(job, check, LABEL, every=2)


def test():
    r = call(API, [{"taskType": "accountManagement", "taskUUID": str(uuid.uuid4()), "operation": "getDetails"}])
    if r.get("errors"):
        raise RuntimeError("Runware: " + "; ".join(x.get("message", "") for x in r["errors"]))
    d = (r.get("data") or [{}])[0]
    bal = d.get("balance") or (d.get("organization") or {}).get("balance")
    return "Connected to Runware" + (f" · balance ${float(bal):.2f}" if bal is not None else "")
