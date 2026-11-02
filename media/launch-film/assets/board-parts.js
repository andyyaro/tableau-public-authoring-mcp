// The board's parts for compositions/s2-board.html, as tables (world px): standard cards, the spec as the README prints it,
// Tableau's five load errors, the three real screenshots and the wires. BOARD_PARTS() writes them into the board's
// placeholders (#cards-A..D, #j-block, #r-rows, #wins, #wires-A..D) and returns the wires by id for the timeline.
// Every string is the project's own (FACTS.md). Card: st = [dot colour, word] status rows; chips; note = a line that
// arrives later. Dot colours follow the overview legend: green = runs without Tableau, indigo = needs Tableau Public on
// this Mac, orange = public and irreversible.
window.BOARD_PARTS = function () {
  // ---- standard cards (world px). st: [dot colour, word] status rows; chips; note (a line that arrives later)
  const CARDS = [
    { g: "A", id: "claude", x: 30, y: 140, w: 300, h: 96, hue: "gray", ic: "text-alignleft", t: "Claude Code", s: "MCP client · over stdio" },
    { g: "A", id: "csv", x: 30, y: 440, w: 300, h: 96, hue: "gray", ic: "list-bullet", t: "sites.csv", s: "12 rows · synthetic fixture" },
    { g: "B", id: "comp", x: 382, y: 278, w: 440, h: 116, hue: "indigo", ic: "gearshape", t: "Compiler", s: "ElementTree XML, never string splicing", st: [["green", ".twb"]] },
    { g: "B", id: "hyper", x: 382, y: 416, w: 440, h: 144, hue: "purple", ic: "square-3-layers-3d-top-filled", t: "Hyper extract", s: "tableauhyperapi, one per CSV", st: [["green", ".hyper"]],
      note: "Error Code 3C242D89 without it" },
    { g: "B", id: "checks", x: 382, y: 582, w: 440, h: 116, hue: "green", ic: "checkmark-circle", t: "Checks", s: "no machine paths · structure valid", st: [["green", "warnings: none"]] },
    { g: "B", id: "pkg", x: 382, y: 720, w: 440, h: 172, hue: "blue", ic: "archivebox", t: "Package", s: "ZIP-slip guarded",
      chips: ["Demo_Map.twb", "Data/sites/sites.hyper", "Data/sites/sites.csv"], st: [["green", ".twbx"]] },
    { g: "C", id: "tab", x: 894, y: 140, w: 520, h: 124, hue: "blue", ic: "square-grid-2x2", t: "Tableau Public 2026.2.0", s: "opened by validate_in_tableau_public",
      st: [["indigo", "opened"], ["indigo", "no error dialog"], ["indigo", "screenshot"]] },
    { g: "D", id: "public", x: 1466, y: 140, w: 424, h: 144, hue: "teal", ic: "globe", t: "public.tableau.com", s: "public and irreversible",
      chips: ["verify_published_workbook"], st: [["orange", "verified: HTTP 200"]] },
    { g: "D", id: "pub", x: 1466, y: 312, w: 424, h: 144, hue: "pink", ic: "square-and-arrow-up", t: "publish_to_tableau_public", s: "Save to Tableau Public As...",
      chips: ["Command+Shift+S"], st: [["orange", "your signed-in session"]] },
    { g: "D", id: "guard", x: 1466, y: 482, w: 424, h: 170, hue: "gray", ic: "lock", t: "Guards", s: "credentials: never read, typed or stored",
      chips: ["confirm_publish: true", "profile"], st: [["orange", "overwrite: false by default"]] },
  ];
  for (const c of CARDS) {
    const st = c.st ? `<div class="a-sts">${c.st.map(([d, w], i) => `<div class="a-st" id="a-${c.id}-st${i + 1}"><i class="a-dot d-${d}"></i><span>${w}</span></div>`).join("")}</div>` : "";
    const chips = c.chips ? `<div class="a-chips" id="a-${c.id}-chips">${c.chips.map((x) => `<span class="a-chip">${x}</span>`).join("")}</div>` : "";
    const note = c.note ? `<div class="a-note" id="a-${c.id}-note">${c.note}</div>` : "";
    document.getElementById(`cards-${c.g}`).insertAdjacentHTML("beforeend",
      `<div class="a-card" id="a-${c.id}" style="left:${c.x}px; top:${c.y}px; width:${c.w}px; height:${c.h}px">` +
      `<div class="a-tile" style="background:var(--system-${c.hue})"><svg class="ic"><use href="#ic-${c.ic}"/></svg></div>` +
      `<div class="a-tx"><div class="a-t">${c.t}</div><div class="a-s">${c.s}</div>${chips}${st}${note}</div></div>`);
  }
  // Tableau's five load errors (VALIDATION_REPORT layer 3), verbatim
  const RULES = ["missing required attribute 'dim-percentage'", "no declaration found for element 'object-graph'",
    "element 'filter' is not allowed for content model", "element 'panes' is not allowed for content model",
    "attribute 'object-id' is not declared for element 'extract'"];
  document.getElementById("r-rows").innerHTML = RULES.map((r) => `<div class="r-row"><span class="r-ic"><svg class="ic r-x"><use href="#ic-xmark-circle-fill"/></svg>` +
    `<svg class="ic r-ok"><use href="#ic-checkmark-circle-fill"/></svg></span><span>${r}</span></div>`).join("");

  // the spec, as the README prints it (pretty-printed; the typo swaps "Status" for "Stauts" in place)
  const K = (k) => `<span class="k">"${k}":</span>`, J = (cls, html) => `<div class="j-l ${cls}">${html}</div>`;
  document.getElementById("j-block").innerHTML = [J("", "{"), J("i1", `${K("name")} "Site Map",`), J("i1", `${K("template")} "map",`),
    J("i1", `${K("data_source")} "sites",`), J("i1", `${K("detail")} [<span class="j-f" id="j-f1">"Site Name"</span>],`),
    J("i1", `${K("color")} <span class="j-f" id="j-f2"><span id="j-color"><span id="j-ok">"Status"</span><span id="j-typo">"Stauts"</span></span></span>,`),
    J("i1", `${K("size")} {`), J("i2", `${K("field")} <span class="j-f" id="j-f3">"Annual Sessions"</span>,`), J("i2", `${K("aggregation")} "Sum" },`),
    J("i1", `${K("title")} "Candidate sites"`), J("", "}")].join("");
  // the real screenshots (docs/images, untouched), each in a white window card with a grey caption
  const WINS = [["dash", 904, 284, 500, "demo_dashboard.png", "Dashboard · two generated sheets, 1200 x 800"],
    ["map", 904, 692, 244, "demo_map.png", "Symbol map · 12 marks"], ["bar", 1160, 692, 244, "demo_bar.png", "Bar chart · colour and labels"]];
  document.getElementById("wins").innerHTML = WINS.map(([id, x, y, w, src, cap]) => `<div id="w-${id}" class="win" style="left:${x}px; top:${y}px; width:${w}px">` +
    `<img src="assets/artifacts/${src}" alt="${cap}, generated from a spec, untouched in Tableau Public" /><div class="w-cap">${cap}</div></div>`).join("");

  // ---- wires (world px)
  const WR = {
    ...KIT.wires(document.getElementById("wires-A"), [
      { id: "w-claude", d: "M330 188 H372", dir: "r" }, { id: "w-spec", d: "M330 308 H346 V236 H372", dir: "r" }, { id: "w-csv", d: "M330 488 H372", dir: "r" }]),
    ...KIT.wires(document.getElementById("wires-B"), [
      { id: "w-v1", d: "M602 256 V268", dir: "d" }, { id: "w-v2", d: "M602 394 V406", dir: "d" },
      { id: "w-v3", d: "M602 560 V572", dir: "d" }, { id: "w-v4", d: "M602 698 V710", dir: "d" }]),
    ...KIT.wires(document.getElementById("wires-C"), [{ id: "w-pkg", d: "M822 806 H858 V202 H884", dir: "r" }]),
    ...KIT.wires(document.getElementById("wires-D"), [
      { id: "w-pub", d: "M1414 202 H1450 V384 H1456", dir: "r", dash: 1 }, { id: "w-public", d: "M1678 312 V294", dir: "u", dash: 1 },
      { id: "w-guard", d: "M1678 482 V466", dir: "u" }]),
  };

  return WR;
};
