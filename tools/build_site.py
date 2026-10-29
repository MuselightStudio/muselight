"""Builds the website zip that's uploaded to Cloudflare Pages.

Every page asks for its scripts and stylesheets with a version made from their contents (app.js?v=1a2b3c4d), so a new
upload is always fetched: the site lets browsers keep .js and .css for hours, and an old script under a new page breaks it.

    python tools/build_site.py [out.zip]     (default: site.zip next to this repo's website folder)
"""
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "website"
ASSET = re.compile(r'((?:src|href)=")(/[^"?#]+\.(?:js|css))(")')


def version(rel):
    return hashlib.sha1((SITE / rel.lstrip("/")).read_bytes()).hexdigest()[:10]


def stamp(html):
    return ASSET.sub(lambda m: f"{m[1]}{m[2]}?v={version(m[2])}{m[3]}" if (SITE / m[2].lstrip("/")).is_file() else m[0], html)


def build(out):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(SITE.rglob("*")):
            if not f.is_file() or f.name == "LAUNCH.md":
                continue
            rel = f.relative_to(SITE).as_posix()
            data = stamp(f.read_text(encoding="utf-8")).encode("utf-8") if f.suffix == ".html" else f.read_bytes()
            z.writestr(rel, data)
    Path(out).write_bytes(buf.getvalue())
    return out


def selftest():
    z = zipfile.ZipFile(io.BytesIO(Path(build(SITE.parent / "site_selftest.zip")).read_bytes()))
    (SITE.parent / "site_selftest.zip").unlink()
    for name in z.namelist():
        if name.endswith(".html"):
            html = z.read(name).decode("utf-8")
            loose = [m[2] for m in ASSET.finditer(html) if (SITE / m[2].lstrip("/")).is_file()]
            assert not loose, (name, "not versioned:", loose)
            for ref, v in re.findall(r'"(/[^"?]+\.(?:js|css))\?v=(\w+)"', html):
                assert v == version(ref), (name, ref)
    assert "index.html" in z.namelist() and "assets/site.css" in z.namelist()
    print("build_site selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        selftest()
    else:
        print(build(sys.argv[1] if len(sys.argv) > 1 else SITE.parent / "site.zip"))
