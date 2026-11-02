// Shared helpers for the scenes (loaded by index.html after vo.js and timing.js).
// KIT.W(S0) returns the cue helper W(line, word, nth): the voice's own time for a word (window.VO), in the scene's local
// seconds (the scene host starts at S0), so a re-voiced or re-slotted line re-times the picture by itself.
// KIT.moves(tl) returns the HIG Native motion vocabulary of the CERFODES film: cards pop (back.out(1.5)), placeholders
// arrive faint and light on their word, status dots slide in, wires draw by stroke-dashoffset with the head at the end.
// KIT.wires(svg, list) draws wires (line + small triangular head; dashed ones revealed through a mask).
(function () {
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const W = (S0) => (k, w, nth = 0) => {
    const alts = w.split("|");
    for (const exact of [true, false]) {
      let c = 0;
      for (const x of window.VO[k].words) {
        const t = norm(x.w);
        if (alts.some((a) => (exact ? t === a : t.startsWith(a)))) { if (c === nth) return x.t0 - S0; c++; }
      }
    }
    return window.VO[k].start - S0;
  };

  const moves = (tl) => {
    const m = {};
    m.pop = (sel, at, dy = 18) => tl.fromTo(sel, { opacity: 0, y: dy, scale: 0.96 }, { opacity: 1, y: 0, scale: 1, duration: 0.6, ease: "back.out(1.5)" }, at);
    m.fade = (sel, at, d = 0.5) => tl.fromTo(sel, { opacity: 0 }, { opacity: 1, duration: d, ease: "power1.out" }, at);
    m.dot = (sel, at) => tl.fromTo(sel, { opacity: 0, x: -8 }, { opacity: 1, x: 0, duration: 0.45, ease: "power2.out" }, at);
    m.chips = (sel, at, gap = 0.12) => tl.fromTo(sel, { opacity: 0, scale: 0.8 }, { opacity: 1, scale: 1, duration: 0.35, ease: "back.out(2)", stagger: gap }, at);
    // placeholder: the empty card shape arrives early (faint); its content lights up on the narrated word
    m.ph = (sel, at) => tl.fromTo(sel, { opacity: 0, scale: 0.97 }, { opacity: 0.5, scale: 1, duration: 0.45, ease: "power2.out" }, at);
    m.light = (sel, at, kids = `${sel} > *`) => {
      tl.to(sel, { opacity: 1, duration: 0.3, ease: "power1.out" }, at);
      tl.fromTo(kids, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.45, ease: "power2.out" }, at);
      tl.to(sel, { scale: 1.035, duration: 0.2, ease: "power2.out" }, at);
      tl.to(sel, { scale: 1, duration: 0.35, ease: "power2.inOut" }, at + 0.2);
    };
    m.titleIn = (sel, at) => tl.fromTo(sel, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, at);
    m.out = (sel, at, d = 0.3, dy = 0) => tl.to(sel, { opacity: 0, y: dy, duration: d, ease: "power1.in" }, at);
    m.wire = (w, at, d = 0.45) => {
      tl.fromTo(`#${w.id}-${w.dash ? "mk" : "ln"}`, { strokeDasharray: 1, strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: d, ease: "power2.inOut" }, at);
      tl.fromTo(`#${w.id}-h`, { opacity: 0 }, { opacity: 1, duration: 0.15 }, at + d - 0.1);
    };
    return m;
  };

  const wires = (svg, list) => {
    const end = (d) => {
      const n = d.match(/-?\d+(\.\d+)?/g).map(Number), cmds = d.match(/[MHV]/g);
      let x = 0, y = 0, k = 0;
      for (const c of cmds) { if (c === "M") { x = n[k++]; y = n[k++]; } else if (c === "H") x = n[k++]; else y = n[k++]; }
      return [x, y];
    };
    const OFF = { r: [1, 0], l: [-1, 0], d: [0, 1], u: [0, -1] };
    const head = (d, dir) => {
      const [ex, ey] = end(d), [ox, oy] = OFF[dir], x = ex + ox * 5.4, y = ey + oy * 5.4, a = 9, b = 6;
      return `M${x} ${y} L${x - ox * a - oy * b} ${y - oy * a - ox * b} L${x - ox * a + oy * b} ${y - oy * a + ox * b} Z`;
    };
    let defs = "", g = "";
    for (const w of list) {
      if (w.dash) {
        defs += `<mask id="${w.id}-m" maskUnits="userSpaceOnUse" x="0" y="0" width="1920" height="1080"><path id="${w.id}-mk" class="mk" d="${w.d}" pathLength="1"/></mask>`;
        g += `<g id="${w.id}"><path class="w dash" d="${w.d}" mask="url(#${w.id}-m)"/><path id="${w.id}-h" class="h" d="${head(w.d, w.dir)}"/></g>`;
      } else {
        g += `<g id="${w.id}"><path id="${w.id}-ln" class="w" d="${w.d}" pathLength="1"/><path id="${w.id}-h" class="h" d="${head(w.d, w.dir)}"/></g>`;
      }
    }
    svg.innerHTML = `<defs>${defs}</defs>${g}`;
    for (const w of list) {
      gsap.set(`#${w.id}-${w.dash ? "mk" : "ln"}`, { strokeDasharray: 1, strokeDashoffset: 1 });
      gsap.set(`#${w.id}-h`, { opacity: 0 });
    }
    return Object.fromEntries(list.map((w) => [w.id, w]));
  };

  window.KIT = { norm, W, moves, wires };
})();
