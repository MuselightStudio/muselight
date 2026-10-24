"""Rebuild the bundled model catalogs for providers that publish their settings only inside their docs
(Kie.ai, PiAPI, MiniMax, SiliconFlow). Run before building the .exe when you want their newest models:

    python tools/build_catalogs.py

Writes providers/catalogs/<provider>.json: [{id, name, cat, desc, path, schema}].
Needs PyYAML (python -m pip install pyyaml); the app itself doesn't.
"""
import json, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import _core as core  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "providers" / "catalogs"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Muselight-catalog"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def specs(md):
    """Every OpenAPI document embedded in a docs page as a yaml code block."""
    for block in re.findall(r"(`{3,4})yaml[^\n]*\n(.*?)\n\1", md, re.S):
        if "openapi:" in block[1][:200]:
            try:
                yield yaml.safe_load(block[1])
            except yaml.YAMLError:
                continue


def posts(spec):
    for path, ops in (spec.get("paths") or {}).items():
        if isinstance(ops, dict) and "post" in ops:
            yield path, ops["post"]


def body_of(spec, post):
    comps = (spec.get("components") or {}).get("schemas") or {}
    content = (post.get("requestBody") or {}).get("content") or {}
    media = content.get("application/json") or next(iter(content.values()), {})
    return core.resolve(media.get("schema") or {}, comps), media.get("example") or {}


def one_value(p):
    p = p or {}
    v = p.get("enum") or ([p["const"]] if "const" in p else None) or ([p["default"]] if p.get("default") else None) or p.get("examples")
    return v if isinstance(v, list) else ([v] if v else [])


def links(index, pattern):
    return [(line, m) for line in index.splitlines() for m in re.findall(pattern, line)]


def kind_from(line):
    head = line.split("[")[0].lower()
    return next((k for k in ("video", "image", "music", "audio", "chat") if k in head), "")


def kie():
    out, index = [], get("https://docs.kie.ai/llms.txt")
    pages = [(l, u) for l, u in links(index, r"\((https://docs\.kie\.ai/market/[^)]+\.md)\)") if "/cn/" not in u and "/common/" not in u
             and "quickstart" not in u and "/chat/" not in u and kind_from(l) not in ("chat",)]

    def one(page):
        line, url = page
        rows = []
        for spec in specs(get(url)):
            for path, post in posts(spec):
                if path != "/api/v1/jobs/createTask":
                    continue
                body, example = body_of(spec, post)
                props = body.get("properties") or {}
                ids = one_value(props.get("model")) or ([example["model"]] if example.get("model") else [])
                inp = props.get("input")
                if not ids or not inp:
                    continue
                for mid in ids:
                    rows.append({"id": mid, "name": post.get("summary") or mid, "cat": kind_from(line), "desc": "", "path": path, "schema": inp})
        return rows
    with ThreadPoolExecutor(12) as ex:
        for rows in ex.map(one, pages):
            out += rows
    return out


def piapi():
    out, index = [], get("https://piapi.ai/docs/llms.txt")
    pages = [u for _, u in links(index, r"\((https://piapi\.ai/docs/[^)]+\.md)\)")
             if not re.search(r"get-task|cancel|penalt|explain|sunset|faq|announce|pricing|billing|changelog|webhook|account|overview|quickstart|"
                              r"endpoints|bulk|checklist|lora-type|available-lora", u)]

    def one(url):
        rows = []
        for spec in specs(get(url)):
            for path, post in posts(spec):
                if path != "/api/v1/task":
                    continue
                body, example = body_of(spec, post)
                props = body.get("properties") or {}
                inp = props.get("input")
                models = one_value(props.get("model")) or ([example.get("model")] if example.get("model") else [])
                tasks = one_value(props.get("task_type")) or ([example.get("task_type")] if example.get("task_type") else [])
                for m in models:
                    for t in tasks:
                        if inp and m and t:
                            rows.append({"id": f"{m}/{t}", "name": f"{post.get('summary') or m} · {t}", "cat": "video" if "video" in f"{m} {t}".lower() else "",
                                         "desc": "", "path": path, "schema": inp, "model": m, "task_type": t})
        return rows
    seen = set()
    with ThreadPoolExecutor(12) as ex:
        for rows in ex.map(one, pages):
            for r in rows:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(r)
    return out


def from_pages(urls, cat_of):
    out = []
    for url in urls:
        for spec in specs(get(url)):
            for path, post in posts(spec):
                body, _ = body_of(spec, post)
                variants = body.get("oneOf") or body.get("anyOf") or [body]
                for v in variants:
                    props = v.get("properties") or {}
                    for mid in one_value(props.get("model")):
                        rest = {**v, "properties": {k: p for k, p in props.items() if k != "model"}, "required": [r for r in v.get("required", []) if r != "model"]}
                        out.append({"id": mid, "name": mid, "cat": cat_of(path), "desc": post.get("summary") or "", "path": path, "schema": rest})
    merged = {}
    for r in out:  # a model on several pages (text to video, image to video…) gets every page's settings; only the prompt stays required
        key = (r["id"], r["path"])
        if key in merged:
            m = merged[key]["schema"]
            m["properties"] = {**r["schema"].get("properties", {}), **m.get("properties", {})}
            m["required"] = [x for x in m.get("required", []) if x in r["schema"].get("required", [])]
        else:
            merged[key] = r
    return list(merged.values())


def minimax():
    pages = [f"https://platform.minimax.io/docs/api-reference/{p}.md" for p in
             ("video-generation-t2v", "video-generation-i2v", "video-generation-fl2v", "video-generation-s2v", "image-generation-t2i", "image-generation-i2i")]
    return from_pages(pages, lambda path: "video" if "video" in path else "image")


def siliconflow():
    return from_pages(["https://docs.siliconflow.com/en/api-reference/images/images-generations.md",
                       "https://docs.siliconflow.com/en/api-reference/videos/videos_submit.md"], lambda path: "video" if "video" in path else "image")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("kie", kie), ("piapi", piapi), ("minimax", minimax), ("siliconflow", siliconflow)):
        try:
            rows = fn()
        except Exception as e:
            print(f"{name}: failed ({e}); keeping the old catalog")
            continue
        if rows:
            (OUT / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(rows)} models")
