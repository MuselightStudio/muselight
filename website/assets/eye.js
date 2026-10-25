// The Muse eye comes alive. The green is the eyeball, the star its pupil, and whatever is behind the logo is the skin.
// The pupil never changes size or shape: it slides towards the pointer, as far as it can without crossing the green's edge.
// To blink, the green's top and bottom close over the pupil like eyelids, so the skin behind shows where it has closed.
// Upgrades every logo it finds (.brand svg, or any svg[data-live-eye]). Still for people who ask for reduced motion.
(() => {
  const ALMOND = "M4 50C22 18 78 18 96 50C78 82 22 82 4 50Z";
  const SPARK = "M50 30C52 44 56 48 70 50C56 52 52 56 50 70C48 56 44 52 30 50C44 48 48 44 50 30Z";
  // each lid's edge curves like a real eyelid; drawn into the eye's mask, so where it covers, the skin shows through
  const UPPER = "M-10 -60H110V50C80 66 20 66 -10 50Z", LOWER = "M-10 160H110V50C80 34 20 34 -10 50Z", OPEN = 52;

  // the star's outline and the eye's top edge as points, to keep the whole pupil inside the eyeball
  const cub = (a, b, c, d, t) => (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d;
  const S = [[50, 30], [52, 44], [56, 48], [70, 50], [56, 52], [52, 56], [50, 70], [48, 56], [44, 52], [30, 50], [44, 48], [48, 44]];
  const star = [];
  for (let s = 0; s < 4; s++) {
    const [p0, p1, p2, p3] = [S[s * 3], S[s * 3 + 1], S[s * 3 + 2], S[(s * 3 + 3) % 12]];
    for (let k = 0; k < 12; k++) star.push([cub(p0[0], p1[0], p2[0], p3[0], k / 12), cub(p0[1], p1[1], p2[1], p3[1], k / 12)]);
  }
  const edge = Array.from({ length: 201 }, (_, k) => [cub(4, 22, 78, 96, k / 200), cub(50, 18, 18, 50, k / 200)]);
  const topAt = x => {
    if (x <= 4 || x >= 96) return 50;
    const i = edge.findIndex(e => e[0] >= x), a = edge[i - 1], b = edge[i];
    return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]);
  };
  const fits = (ox, oy) => star.every(([x, y]) => { const t = topAt(x + ox); return y + oy >= t + 1.5 && y + oy <= 100 - t - 1.5; });
  const place = (pupil, dx, dy) => {  // as far along (dx, dy) as fits
    let lo = 0, hi = 1;
    if (fits(dx, dy)) lo = 1;
    else for (let i = 0; i < 14; i++) { const m = (lo + hi) / 2; fits(dx * m, dy * m) ? lo = m : hi = m; }
    pupil.setAttribute("transform", `translate(${(dx * lo).toFixed(2)} ${(dy * lo).toFixed(2)})`);
  };

  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const eyes = [...document.querySelectorAll(".brand svg, svg[data-live-eye]")].map((svg, i) => {
    const id = "ml-eye-" + i;
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.innerHTML = `<defs><linearGradient id="${id}g" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#d4f5e2"/>`
      + `<stop offset=".5" stop-color="#3ccf8e"/><stop offset="1" stop-color="#128a5c"/></linearGradient>`
      + `<mask id="${id}m" maskUnits="userSpaceOnUse" x="-10" y="-10" width="120" height="120"><rect x="-10" y="-10" width="120" height="120" fill="#fff"/>`
      + `<path class="ml-pupil" d="${SPARK}" fill="#000"/>`
      + `<path class="ml-lid" d="${UPPER}" fill="#000" style="transform: translateY(-${OPEN}px); transition: transform 90ms ease-in"/>`
      + `<path class="ml-lid" d="${LOWER}" fill="#000" style="transform: translateY(${OPEN}px); transition: transform 90ms ease-in"/></mask></defs>`
      + `<path d="${ALMOND}" fill="url(#${id}g)" mask="url(#${id}m)"/>`;
    return { svg, pupil: svg.querySelector(".ml-pupil"), lids: svg.querySelectorAll(".ml-lid") };
  });
  if (still || !eyes.length) return;

  const lids = shut => eyes.forEach(e => e.lids.forEach((l, i) => l.style.transform = `translateY(${shut ? 0 : (i ? OPEN : -OPEN)}px)`));
  const blink = () => { lids(true); setTimeout(() => lids(false), 150); };
  (function later() {
    const busy = document.body.classList.contains("busy");  // the Windows app blinks more while it's making something
    setTimeout(() => { blink(); if (Math.random() < .2) setTimeout(blink, 320); later(); }, (busy ? 1200 : 3000) + Math.random() * (busy ? 1500 : 3000));
  })();

  let frame = 0, px = 0, py = 0;
  const look = () => {
    frame = 0;
    for (const e of eyes) {
      const r = e.svg.getBoundingClientRect();
      const dx = px - (r.left + r.width / 2), dy = py - (r.top + r.height / 2), d = Math.hypot(dx, dy) || 1;
      const pull = Math.min(1, d / 180) * 30;  // close to the logo it eases off, so it doesn't jitter under the pointer
      place(e.pupil, dx / d * pull, dy / d * pull);
    }
  };
  addEventListener("pointermove", ev => {
    if (ev.pointerType !== "mouse") return;
    px = ev.clientX; py = ev.clientY;
    frame ||= requestAnimationFrame(look);
  }, { passive: true });
  document.documentElement.addEventListener("pointerleave", () => eyes.forEach(e => place(e.pupil, 0, 0)));
})();
