"""Draws Muselight's icons: every size the window, taskbar and installer may ask for, each drawn for its own size.

Small sizes are not shrunk from the big one (that is what made the taskbar icon soft): the mark is laid out on that size's
own pixel grid, drawn 8x larger and filtered down, so its edges land on whole pixels. Run: python tools/make_icons.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "icons"
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 192, 256, 512]
STOPS = [(212, 245, 226), (60, 207, 142), (18, 138, 92)]  # pale jade, emerald, deep forest


def gradient(n):
    g = Image.new("RGB", (n, n)); px = g.load()
    for y in range(n):
        for x in range(n):
            t = (x * 0.55 + (n - 1 - y) * 0.45) / (n - 1)
            a, b, k = (STOPS[0], STOPS[1], t / .5) if t < .5 else (STOPS[1], STOPS[2], (t - .5) / .5)
            px[x, y] = tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))
    return g


def cubic(p0, p1, p2, p3, k=64):
    """Points along a cubic Bézier curve (PIL draws polygons, not curves)."""
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * e for a, b, c, e in zip(p0, p1, p2, p3))
            for t in (i / k for i in range(k))]


# the Muse eye, in the same 100x100 units as the logo in studio_ui.html: an eye-shaped lens with a spark for its pupil
EYE = cubic((4, 50), (22, 18), (78, 18), (96, 50)) + cubic((96, 50), (78, 82), (22, 82), (4, 50))
SPARK = [((50, 30), (52, 44), (56, 48), (70, 50)), ((70, 50), (56, 52), (52, 56), (50, 70)),
         ((50, 70), (48, 56), (44, 52), (30, 50)), ((30, 50), (44, 48), (48, 44), (50, 30))]


def icon(n, tile_bg=True):
    small = n <= 64
    s = 8 if n <= 512 else 4  # supersampling
    N = n * s
    tile = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    if tile_bg:
        d.rounded_rectangle([0, 0, N - 1, N - 1], radius=round(N * (0.22 if small else 0.23)), fill=(11, 17, 14, 255),
                            outline=None if small else (30, 44, 37, 255), width=max(1, N // 128))
    # small icons get a wider eye and a bigger spark-pupil, so the pupil still shows at 16 px
    width = n * (0.88 if small else 0.74 if tile_bg else 0.96)  # the eye alone fills its canvas
    f = width / 92 * s
    ox, oy = N / 2 - 50 * f, N / 2 - 50 * f
    pupil = 1.65 if n <= 24 else 1.35 if small else 1.0
    m = Image.new("L", (N, N), 0)
    md = ImageDraw.Draw(m)
    md.polygon([(ox + x * f, oy + y * f) for x, y in EYE], fill=255)
    md.polygon([(ox + (50 + (x - 50) * pupil) * f, oy + (50 + (y - 50) * pupil) * f) for seg in SPARK for x, y in cubic(*seg, k=32)], fill=0)
    tile.paste(gradient(N).convert("RGBA"), (0, 0), m)
    return tile.resize((n, n), Image.BOX)  # BOX: an exact average of the 8x8 block, so no ringing at the edges


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    imgs = {n: icon(n) for n in SIZES}
    for n, im in imgs.items():
        im.save(OUT / f"icon_{n}.png")
    ico = [imgs[n] for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    ico[-1].save(ROOT / "muselight.ico", format="ICO", sizes=[i.size for i in ico], append_images=ico[:-1])
    print("icons:", ", ".join(map(str, SIZES)))
    # brand files for profile pictures, listings and anywhere else the logo is uploaded
    brand = ROOT / "brand"
    brand.mkdir(exist_ok=True)
    icon(1024).save(brand / "logo_tile_1024.png")
    icon(1024, tile_bg=False).save(brand / "logo_eye_1024.png")
    icon(120).save(brand / "logo_tile_120.png")  # Google's sign-in screen wants 120 x 120
    print("brand: logo_tile_1024, logo_eye_1024, logo_tile_120")
