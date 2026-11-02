"""Write the scene windows (sound/timing.json) and the burned-in subtitles (assets/vo.js) into index.html.

    python3 -I build.py

Each scene host's data-start/data-duration and the root duration come from the same numbers the scenes read at
runtime (window.TM in assets/timing.js), so the two can never drift apart.

HOSTS maps a scene host's id in index.html to its window in sound/timing.json. A value can also be a pair of keys
("s2", "s6"): the host then runs from the first window's start to the second window's end (the one big board that
the camera glides across from the spec to the overview). Ids that are not in index.html are reported and skipped.

Subtitles (the CERFODES rules, ported from its retime.mjs): the script's own words (vo.js "text"), lined up with the
voice's word times, cut into cues of at most 2 lines of at most 42 characters, preferring sentence ends, then commas.
Each cue starts 0.05 s before its first word and ends 0.3 s after its last (at least 1.0 s on screen); a gap under
0.7 s to the next cue is bridged so the pill does not blink. ONSCREEN lines (the end card's two lines, already large
on screen) get no pill. The same cues, with the end card's lines, go to renders/tableau-mcp-v1.en.vtt (WebVTT).
The icon sprite is written separately by scripts/build-icons.mjs.
"""
import html, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TM = json.loads((ROOT / "sound/timing.json").read_text())
HOSTS = {"s1-hook": "s1", "s2-board": ("s2", "s6"), "s2-titles": ("s2", "s6"), "s7-end": "s7"}
ONSCREEN = {"v13", "v14"}
VTT = "renders/tableau-mcp-v1.en.vtt"
MAX_CHARS, MAX_LINES, LEAD, TAIL, MIN_DUR, BRIDGE = 42, 2, 0.05, 0.3, 1.0, 0.7
# word pairs a line break should not split (a name or a phrase read as one); "*" = any next word
NOBREAK = {("hyper", "extract"), ("save", "flow"), ("tableau", "public"), ("every", "field"), ("the", "*"), ("a", "*")}
r = lambda x: f"{x:.3f}".rstrip("0").rstrip(".")
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())

s = (ROOT / "index.html").read_text()
done = []
for host, key in HOSTS.items():
    a, b = (TM[key[0]][0], TM[key[1]][1]) if isinstance(key, tuple) else TM[key]
    s, n = re.subn(rf'(<div id="{host}"[^>]*?data-start=")[^"]*(" data-duration=")[^"]*(")', rf"\g<1>{r(a)}\g<2>{r(b - a)}\g<3>", s)
    if n != 1:
        print(f"warning: no scene host {host!r} in index.html (found {n})")
        continue
    done.append(f"{host} {r(a)}-{r(b)}")
s, n = re.subn(r'(<div id="main"[^>]*?data-duration=")[^"]*(")', rf"\g<1>{r(TM['duration'])}\g<2>", s); assert n == 1
s, n = re.subn(r'(<audio id="soundtrack"[^>]*?data-duration=")[^"]*(")', rf"\g<1>{r(TM['duration'])}\g<2>", s); assert n == 1

# ---- subtitles
vo_src = (ROOT / "assets/vo.js").read_text()
VO = json.loads(vo_src[vo_src.index("{"): vo_src.rindex("}") + 1])


def align(text, heard):
    """The script's words, each with the time of the heard word(s) it matches ("signed-in" = "signed" + "in")."""
    out, j = [], 0
    for w in text.split():
        want, acc, t0, t1 = norm(w), "", None, None
        while j < len(heard) and len(acc) < len(want):
            acc += norm(heard[j]["w"])
            t0 = heard[j]["t0"] if t0 is None else t0
            t1 = heard[j]["t1"]
            j += 1
        if acc != want:
            print(f"warning: subtitle alignment: script {w!r} vs heard {acc!r}")
        out.append({"w": w, "t0": t0, "t1": t1})
    return out


def wrap(words):
    text = " ".join(words)
    if len(text) <= MAX_CHARS:
        return [text]
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        if len(a) > MAX_CHARS or len(b) > MAX_CHARS:
            continue
        pair = (norm(words[k - 1]), norm(words[k]))
        glued = pair in NOBREAK or (pair[0], "*") in NOBREAK
        score = max(len(a), len(b)) - (6 if re.search(r"[,:;.]$", words[k - 1]) else 0) + (12 if glued else 0)
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1] if (MAX_LINES >= 2 and best) else None


def chunk(words):
    n = len(words)
    dp, frm = [0.0] + [float("inf")] * n, [-1] * (n + 1)
    end_cost = lambda w, last: 0 if (last or re.search(r"[.?!]$", w)) else (1 if re.search(r"[,:;]$", w) else 6)
    for i in range(1, n + 1):
        for j in range(max(0, i - 24), i):
            seg = [x["w"] for x in words[j:i]]
            if not wrap(seg):
                continue
            ln = len(" ".join(seg))
            inner = sum(1 for w in seg[:-1] if re.search(r"[.?!]$", w))
            c = dp[j] + end_cost(seg[-1], i == n) + (4 if ln < 22 else 0) + inner * (1.5 if ln <= 52 else 8) + 1
            if c < dp[i]:
                dp[i], frm[i] = c, j
    out, i = [], n
    while i > 0:
        out.insert(0, words[frm[i]:i])
        i = frm[i]
    return out


def make_cues(skip):
    cues = []
    for k, line in VO.items():
        if k in skip:
            continue
        for ws in chunk(align(line["text"], line["words"])):
            cues.append({"line": k, "lines": wrap([x["w"] for x in ws]), "start": ws[0]["t0"] - LEAD, "end": ws[-1]["t1"] + TAIL})
    for i, c in enumerate(cues):
        nx = cues[i + 1] if i + 1 < len(cues) else None
        if c["end"] - c["start"] < MIN_DUR:
            c["end"] = c["start"] + MIN_DUR
        if nx and nx["start"] - c["end"] < BRIDGE:
            c["end"] = nx["start"] - 0.04
        if nx and c["end"] > nx["start"] - 0.04:
            c["end"] = nx["start"] - 0.04
    return cues


cues = make_cues(ONSCREEN)
sub_html = "\n".join(
    f'        <div id="sub-{i + 1}" class="clip sub subtitle-cue" data-start="{r(c["start"])}" data-duration="{r(c["end"] - c["start"])}" '
    f'data-track-index="5">{html.escape(chr(10).join(c["lines"]), quote=False)}</div>'
    for i, c in enumerate(cues))
block = f'<!-- HF:SUBS (generated by build.py from assets/vo.js, do not hand-edit) -->\n      <div id="subtitles">\n{sub_html}\n      </div>\n      <!-- /HF:SUBS -->'
s, n = re.subn(r"<!-- HF:SUBS[\s\S]*?<!-- /HF:SUBS -->", lambda m: block, s); assert n == 1

(ROOT / "index.html").write_text(s)

# ---- the WebVTT sidecar: the whole narration (the pill's cues, plus the end card's two spoken lines)
ts = lambda x: f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{x % 60:06.3f}"
vtt = make_cues(set())
(ROOT / "renders").mkdir(exist_ok=True)
(ROOT / VTT).write_text("WEBVTT\n\n" + "\n".join(f"{i + 1}\n{ts(c['start'])} --> {ts(c['end'])}\n" + "\n".join(c["lines"]) + "\n"
                                                  for i, c in enumerate(vtt)))
print("index.html:", ", ".join(done), f"| {TM['duration']} s | {len(cues)} subtitle cues | {VTT}: {len(vtt)} cues")
for c in cues:
    print(f"  {c['start']:6.2f}-{c['end']:6.2f}  {' / '.join(c['lines'])}")
