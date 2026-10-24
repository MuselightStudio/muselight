"""Run any fal.ai model and save its outputs.

Usage:
  python fal_run.py MODEL_ID key=value key=@file key[]=@a.jpg key[]=@b.jpg
  python fal_run.py --selftest

  key=value      text, or a number/true/false
  key=@file      a local file, sent as an upload
  key[]=...      repeat to build a list (e.g. image_urls[]=@a.jpg)

The API key is read from the FAL_KEY environment variable.
Results are printed and any output files are saved to ./outputs.
"""
import base64, json, mimetypes, os, sys, time, urllib.parse, urllib.request
from pathlib import Path


def to_value(raw):
    if raw.startswith("@"):
        path = Path(raw[1:])
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        # ponytail: files are inlined as data URIs; very large videos may be rejected — switch to fal storage upload if so.
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    try:
        return json.loads(raw)  # numbers, true/false
    except ValueError:
        return raw


def parse_args(pairs):
    body = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            sys.exit(f"Bad argument {pair!r}: expected key=value")
        if key.endswith("[]"):
            body.setdefault(key[:-2], []).append(to_value(raw))
        else:
            body[key] = to_value(raw)
    return body


def request(url, key, body=None):
    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"fal error {e.code}: {e.read().decode(errors='replace')}")


def output_urls(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "url" and isinstance(v, str) and v.startswith("http"):
                yield v
            elif k not in ("metadata", "input", "inputs", "input_videos", "input_images", "request"):  # details that echo the inputs back
                yield from output_urls(v)
    elif isinstance(node, list):
        for v in node:
            yield from output_urls(v)


assert list(output_urls({"video": {"url": "https://a/out.mp4"}, "metadata": {"input_videos": [{"url": "https://a/in.mp4"}]}})) == ["https://a/out.mp4"]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    key = os.environ.get("FAL_KEY")
    if not key:
        sys.exit("FAL_KEY is not set. See the setup steps.")
    model, body = sys.argv[1], parse_args(sys.argv[2:])

    job = request(f"https://queue.fal.run/{model}", key, body)
    print("Submitted, request id:", job["request_id"])
    while True:
        status = request(job["status_url"], key)["status"]
        if status == "COMPLETED":
            break
        print("Status:", status)
        time.sleep(3)

    result = request(job["response_url"], key)
    print(json.dumps(result, indent=2))
    out = Path("outputs")
    out.mkdir(exist_ok=True)
    for url in output_urls(result):
        name = Path(urllib.parse.urlparse(url).path).name or "output"
        dest = out / f"{int(time.time())}_{name}"
        urllib.request.urlretrieve(url, dest)
        print("Saved", dest)


def selftest():
    body = parse_args(["prompt=a cat", "num_images=2", "sync=true", "image_urls[]=@" + __file__])
    assert body["prompt"] == "a cat" and body["num_images"] == 2 and body["sync"] is True
    assert body["image_urls"][0].startswith("data:text/x-python;base64,")
    assert list(output_urls({"images": [{"url": "https://x/a.png"}], "video": {"url": "https://x/v.mp4"}})) == [
        "https://x/a.png", "https://x/v.mp4"]
    print("selftest ok")


if __name__ == "__main__":
    selftest() if sys.argv[1:] == ["--selftest"] else main()
