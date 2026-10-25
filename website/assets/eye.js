// The Muse eye comes alive: it blinks now and then, and its spark-pupil looks towards the pointer.
// Upgrades every logo it finds (.brand svg, or any svg[data-live-eye]). Off for people who ask for reduced motion.
(() => {
  const ALMOND = "M4 50C22 18 78 18 96 50C78 82 22 82 4 50Z";
  const SPARK = "M50 30C52 44 56 48 70 50C56 52 52 56 50 70C48 56 44 52 30 50C44 48 48 44 50 30Z";
  const REACH_X = 10, REACH_Y = 3;  // how far the pupil travels, in logo units; more and it would poke out of the eye
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const eyes = [...document.querySelectorAll(".brand svg, svg[data-live-eye]")].map((svg, i) => {
    const id = "ml-eye-" + i;
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.innerHTML = `<defs><linearGradient id="${id}g" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#d4f5e2"/>`
      + `<stop offset=".5" stop-color="#3ccf8e"/><stop offset="1" stop-color="#128a5c"/></linearGradient>`
      + `<mask id="${id}m" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><rect width="100" height="100" fill="#fff"/>`
      + `<path class="ml-pupil" d="${SPARK}" fill="#000" style="transition: transform .25s ease-out"/></mask></defs>`
      + `<g class="ml-lid mk-eye" style="transform-box: fill-box; transform-origin: center; transition: transform .08s ease-in">`
      + `<path d="${ALMOND}" fill="url(#${id}g)" mask="url(#${id}m)"/></g>`;
    return { svg, pupil: svg.querySelector(".ml-pupil"), lid: svg.querySelector(".ml-lid") };
  });
  if (still || !eyes.length) return;

  const blink = () => {
    eyes.forEach(e => e.lid.style.transform = "scaleY(.08)");
    setTimeout(() => eyes.forEach(e => e.lid.style.transform = ""), 110);
  };
  (function later() {
    setTimeout(() => { blink(); if (Math.random() < .2) setTimeout(blink, 260); later(); }, 3000 + Math.random() * 4000);
  })();

  let frame = 0, px = 0, py = 0;
  const look = () => {
    frame = 0;
    for (const e of eyes) {
      const r = e.svg.getBoundingClientRect();
      const dx = px - (r.left + r.width / 2), dy = py - (r.top + r.height / 2), d = Math.hypot(dx, dy) || 1;
      const pull = Math.min(1, d / 240);  // close to the logo it eases off, so it doesn't jitter under the pointer
      e.pupil.style.transform = `translate(${(dx / d) * pull * REACH_X}px, ${(dy / d) * pull * REACH_Y}px)`;
    }
  };
  addEventListener("pointermove", ev => {
    if (ev.pointerType !== "mouse") return;
    px = ev.clientX; py = ev.clientY;
    frame ||= requestAnimationFrame(look);
  }, { passive: true });
  document.documentElement.addEventListener("pointerleave", () => eyes.forEach(e => e.pupil.style.transform = ""));
})();
