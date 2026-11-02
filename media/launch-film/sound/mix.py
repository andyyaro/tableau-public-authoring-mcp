"""The Tableau Public Authoring MCP soundtrack: Kokoro af_heart, "Pop 07" (Grigoriy Nuzhny) as a quiet bed, soft effects.

    python3 -I sound/mix.py [--stems DIR]

Inputs: assets/audio/music.wav (sound/music.py), narration/chosen/<id>.wav + narration/words.json (narration/pick.py),
sound/sfx-src/mixkit-<id>.mp3 (Mixkit free sound effects, same licence as the music).
Outputs:
- assets/audio/mix.wav: the soundtrack, about -16 LUFS, true peak under -1.5 dBTP.
- assets/audio/vo.wav: the voice alone.
- assets/vo.js: window.VO, each line's start/end and word times in film seconds.
- assets/timing.js and sound/timing.json: window.TM, the scene windows. Every scene reads its start from it, and
  build.py writes the same numbers into index.html.
- a level report (printed): speech loudness, the bed under the voice and between lines, the mix and its true peak.

Levels (Andy: "the sound should not be too loud, just present, the voice should be clear"):
- The voice is the loudest thing. The bed is set 9 dB under the speech (both measured over the spans she speaks), then
  ducked 4.5 dB more while she speaks (40 ms attack, 450 ms release): about 13.5 dB under her words.
- Each effect's loudest 100 ms sits 3-6 dB over the bed under it (both K-weighted, measured per effect) and its peak
  lands one frame after its picture. --stems DIR writes the voice, bed and effects (final gain) for checking.
"""
import json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf, librosa
from scipy.signal import lfilter

ROOT = Path(__file__).resolve().parent.parent
SR = 48000
G = json.loads((ROOT / "sound/grid.json").read_text())
DROP, END_CARD, DUR = G["drop"], G["end_card"], G["duration"]

# each line's start in film seconds (the clip's speech starts 0.06 s in). The hook sits on the breakdown; the groove
# enters on the drop (8.0 s) exactly on the "T" of "Tableau" (v03 at 7.94); the outro lands on the end card (58.667).
# Film bar lines are n * 8/3 s (90 BPM). Breaths inside a scene 0.42-0.61 s; longer gaps leave room for the camera.
SLOTS = {"v01": 0.70, "v02": 3.70, "v03": 7.94, "v04": 13.40, "v05": 15.50, "v06": 21.85, "v07": 29.80,
         "v08": 34.35, "v09": 37.80, "v10": 43.80, "v11": 48.15, "v12": 53.90, "v13": 59.85, "v14": 62.35}
# scene windows (film seconds), on bar lines (8/3 s) or, where a scene needs one more beat, on a beat line (2/3 s):
#   s1 hook + title      0       12.667  (bar 4 beat 4: the chip that lands on "publishes" holds 1.7 s)
#   s2 spec + dry run    12.667  21.333  (bar 8)
#   s3 compile + build   21.333  29.333  (bar 11)
#   s4 the real app      29.333  43.333  (bar 16 beat 2: the screenshots hold 1.5 s after v09)
#   s5 publish + guards  43.333  53.333  (bar 20: the overview whoosh also covers the music's only repeat seam)
#   s6 overview + tests  53.333  59.4    (runs on 0.73 s under the end card while the board fades)
#   s7 end card          58.667  67.5    (bar 22: the track's outro; its own fade, then 2.5 s more)
SCENES = {"s1": [0, 12.667], "s2": [12.667, 21.333], "s3": [21.333, 29.333], "s4": [29.333, 43.333],
          "s5": [43.333, 53.333], "s6": [53.333, 59.4], "s7": [END_CARD, DUR]}


def lufs(path):
    out = subprocess.run(["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summ = out[out.rfind("Summary:"):]
    i = float(summ.split("I:")[1].split("LUFS")[0])
    tp = float(summ.split("Peak:")[1].split("dBFS")[0]) if "Peak:" in summ else 0.0
    return i, tp


def to_stereo(y):
    return np.vstack([y, y]) if y.ndim == 1 else y


def load(path, sr=SR):
    y, s = sf.read(path, always_2d=True)
    y = y.T.astype(np.float64)
    if s != sr:
        y = np.vstack([librosa.resample(ch, orig_sr=s, target_sr=sr) for ch in y])
    return y


def main():
    words = json.loads((ROOT / "narration/words.json").read_text())
    music = load(ROOT / "assets/audio/music.wav")
    n = music.shape[1]

    # ---------------------------------------------------------------- the voice
    vo = np.zeros(n)
    meta, prev_end = {}, 0.0
    for key, t0 in SLOTS.items():
        y = load(ROOT / f"narration/chosen/{key}.wav").mean(0)
        if t0 < prev_end + 0.25:
            print(f"warning: {key} starts {prev_end + 0.25 - t0:.2f} s too early", file=sys.stderr)
        a = int(round(t0 * SR)); b = min(n, a + len(y))
        vo[a:b] += y[: b - a]
        end = t0 + len(y) / SR
        meta[key] = {"start": round(t0, 3), "end": round(end, 3), "text": words[key]["text"],
                     "words": [{"w": w["w"], "t0": round(t0 + w["t0"], 3), "t1": round(t0 + w["t1"], 3)} for w in words[key]["words"]]}
        prev_end = end
    tmp = Path(tempfile.mkdtemp())
    sf.write(tmp / "vo_raw.wav", vo.astype(np.float32), SR)
    # Kokoro is clean and bright already: a high-pass, a touch of presence, light de-essing and compression
    chain = ("highpass=f=80,equalizer=f=3000:t=q:w=1.2:g=1.5,equalizer=f=250:t=q:w=1.0:g=-1,"
             "deesser=i=0.2:f=0.5,acompressor=threshold=0.1:ratio=2.5:attack=10:release=150:makeup=1.3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp / "vo_raw.wav"), "-af", chain, "-ar", str(SR),
                    str(ROOT / "assets/audio/vo.wav")], check=True)
    vo = load(ROOT / "assets/audio/vo.wav").mean(0)[:n]
    vo = np.pad(vo, (0, n - len(vo)))

    # ---------------------------------------------------------------- the bed: quieter, less boom, ducked by the voice
    sf.write(tmp / "m.wav", music.T.astype(np.float32), SR)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp / "m.wav"), "-af",
                    "bass=g=-4:f=110:w=0.7,equalizer=f=2500:t=q:w=1.5:g=-2", str(tmp / "m2.wav")], check=True)
    bed = load(tmp / "m2.wav")
    # speech at -16 LUFS and the bed 9 dB under it before ducking, both measured over the spans she speaks
    # (so the quiet breakdown, the gaps and the fade do not skew either number)
    spans = [(m["start"], m["end"]) for m in meta.values()]
    vo *= 10 ** ((-16 - span_lufs(tmp, vo, spans, "v")) / 20)
    bed *= 10 ** ((-25 - span_lufs(tmp, bed, spans, "b")) / 20)
    # duck: -4.5 dB under the voice, 40 ms attack, 450 ms release (followed at 1 kHz, then interpolated)
    hop = SR // 1000
    env = np.sqrt(np.convolve(vo ** 2, np.ones(int(0.05 * SR)) / int(0.05 * SR), "same"))[::hop]
    on = (env > 10 ** (-45 / 20)).astype(float)
    g = np.empty(len(on)); state = 0.0
    att, rel = 1 - np.exp(-1 / (0.04 * 1000)), 1 - np.exp(-1 / (0.45 * 1000))
    for i, target in enumerate(on):
        state += (att if target > state else rel) * (target - state)
        g[i] = state
    g = np.interp(np.arange(n), np.arange(len(g)) * hop, g)
    duck = 10 ** (-4.5 * g / 20)
    bed *= duck

    # ---------------------------------------------------------------- effects
    sfx = np.zeros((2, n))
    TMd = {"drop": DROP, **SCENES}
    W = word_finder(meta)
    bed_k = kweight(bed.mean(0))   # the ducked bed as the ear weighs it: each effect is set against the bed under it
    for t, name, over_db, pitch in sfx_events(W, TMd, meta):
        place(sfx, name, t, over_db, pitch, bed_k)

    # ---------------------------------------------------------------- sum, level, limit
    mix = bed + sfx + np.vstack([vo, vo])
    sf.write(tmp / "mix.wav", mix.T.astype(np.float32), SR)
    mi, _ = lufs(tmp / "mix.wav")
    mix *= 10 ** ((-16 - mi) / 20)
    sf.write(tmp / "mix2.wav", mix.T.astype(np.float32), SR)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp / "mix2.wav"), "-af", "alimiter=limit=0.79:attack=3:release=60:level=disabled",
                    "-ar", str(SR), str(ROOT / "assets/audio/mix.wav")], check=True)
    fi, tp = lufs(ROOT / "assets/audio/mix.wav")
    report = level_report(tmp, vo * 10 ** ((-16 - mi) / 20), (bed + sfx) * 10 ** ((-16 - mi) / 20), meta)
    if "--stems" in sys.argv:   # the three parts at the final mix gain (before the limiter), for checking the effects
        d = Path(sys.argv[sys.argv.index("--stems") + 1]); d.mkdir(parents=True, exist_ok=True)
        k = 10 ** ((-16 - mi) / 20)
        for name, y in [("vo", np.vstack([vo, vo])), ("bed", bed), ("sfx", sfx)]:
            sf.write(d / f"{name}.wav", (y * k).T.astype(np.float32), SR)
        (d / "events.json").write_text(json.dumps(sfx_events(W, TMd, meta)))

    (ROOT / "assets/vo.js").write_text("window.VO = " + json.dumps(meta) + ";\n")
    tm = {"drop": DROP, "end_card": END_CARD, "track_ending": G["track_ending"], "duration": DUR, **SCENES}
    (ROOT / "assets/timing.js").write_text("window.TM = " + json.dumps(tm) + ";\n")
    (ROOT / "sound/timing.json").write_text(json.dumps(tm, indent=1))
    print(f"mix.wav {DUR} s, {fi:.1f} LUFS, true peak {tp:.1f} dBTP; voice, bed and {len(sfx_events(W, TMd, meta))} effects")
    print("lines: " + ", ".join(f"{k} {m['start']:.2f}-{m['end']:.2f}" for k, m in meta.items()))
    print(report)


def span_lufs(tmp, y, spans, name):
    """Integrated loudness of y over the given (start, end) film spans, joined end to end."""
    y2 = np.vstack([y, y]) if y.ndim == 1 else y
    f = tmp / f"span_{name}.wav"
    sf.write(f, np.concatenate([y2[:, int(a * SR): int(b * SR)] for a, b in spans], axis=1).T.astype(np.float32), SR)
    return lufs(f)[0]


def level_report(tmp, vo, bed, meta):
    """Loudness of the voice and of the bed (with effects) over the spans she speaks, and of the bed between lines
    (hook, gaps over 0.6 s; the last 2.5 s fade excluded), all at the final mix gain (before the limiter)."""
    spans = [(m["start"], m["end"]) for m in meta.values()]
    gaps = [(a[1] + 0.25, b[0] - 0.05) for a, b in zip(spans, spans[1:]) if b[0] - a[1] > 0.6]
    gaps = [(0.4, spans[0][0] - 0.05)] + gaps
    out = {name: span_lufs(tmp, y, sp, name) for name, y, sp in
           [("speech", vo, spans), ("bed_under_voice", bed, spans), ("bed_between_lines", bed, gaps)]}
    return (f"levels: speech {out['speech']:.1f} LUFS | bed under the voice {out['bed_under_voice']:.1f} LUFS "
            f"({out['speech'] - out['bed_under_voice']:.1f} dB under) | bed between lines {out['bed_between_lines']:.1f} LUFS "
            f"({out['speech'] - out['bed_between_lines']:.1f} dB under; duck depth {out['bed_between_lines'] - out['bed_under_voice']:.1f} dB)")


def word_finder(meta):
    norm = lambda s: "".join(c for c in s.lower() if c.isalnum())
    def W(k, w, nth=0):
        alts = w.split("|")
        ws = meta[k]["words"]
        for exact in (True, False):
            c = 0
            for x in ws:
                t = norm(x["w"])
                if any((t == a) if exact else t.startswith(a) for a in alts):
                    if c == nth: return x["t0"]
                    c += 1
        print(f"warning: no word {w!r} in {k}", file=sys.stderr)
        return meta[k]["start"]
    return W


SFX = {  # the film's whole vocabulary (SPEC.md SOUND), secure-data-hub's sounds: nothing harsh, no typing
    "pop": "mixkit-2357.mp3",        # a soft pop: a card or a part arriving or lighting; the soft hit on the drop
    "tick": "mixkit-1120.mp3",       # a step or a counter: a status dot, a check, a row
    "pop_low": "mixkit-3005.mp3",    # always at pitch 0.8: a refusal or an error
    "whoosh_air": "mixkit-1492.mp3", # travel: the camera's moves between zones (soft) and the two big ones (into, out)
    "riser": "mixkit-2408.mp3",      # once: the swell into the drop
}
_cache = {}


def clip(name):
    if name not in _cache:
        y = load(ROOT / "sound/sfx-src" / SFX[name])
        if name == "riser":    # let it swell in from nothing (as in secure-data-hub)
            f = int(1.2 * SR); y[:, :f] *= np.linspace(0, 1, f) ** 2
        peak = np.argmax(np.convolve(np.abs(y).mean(0), np.ones(240) / 240, "same")) / SR
        rms = 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9)
        _cache[name] = (y, peak, rms)
    return _cache[name]


def kweight(y):
    """BS.1770 K-weighting at 48 kHz (the loudness meters' ear: a high shelf, then a high-pass)."""
    y = lfilter([1.53512485958697, -2.69169618940638, 1.19839281085285], [1, -1.69065929318241, 0.73248077421585], y)
    return lfilter([1, -2, 1], [1, -1.99004745483398, 0.99007225036621], y)


def kpeak(y):
    """The loudest 100 ms of a mono signal, K-weighted RMS in dB."""
    w = int(0.1 * SR)
    return 10 * np.log10(np.convolve(kweight(y) ** 2, np.ones(w) / w, "valid").max() + 1e-24)


def place(out, name, t, over_db, pitch, bed_k):
    y, peak, rms = clip(name)
    if pitch != 1.0:   # small pitch steps rotate repeated sounds (resampling also shortens or lengthens them)
        y = np.vstack([librosa.resample(ch, orig_sr=SR, target_sr=int(SR / pitch)) for ch in y]); peak /= pitch
    # "+4" = its loudest 100 ms sits 4 dB over the bed around its peak (both K-weighted; the bed over 1.2 s, ducked),
    # so the hook's quiet breakdown and the full groove get effects at the same distance from the music
    tp = t + 1 / 30
    seg = bed_k[max(0, int((tp - 0.6) * SR)): int((tp + 0.6) * SR)]
    bed_db = 10 * np.log10(np.mean(seg ** 2) + 1e-24)
    y = y * 10 ** ((bed_db + over_db - kpeak(y.mean(0))) / 20)
    a = int(round((tp - peak) * SR))   # its peak one frame after the picture
    s0 = max(0, -a); a = max(0, a)
    b = min(out.shape[1], a + y.shape[1] - s0)
    out[:, a:b] += y[:, s0: s0 + (b - a)]


def sfx_events(W, TM, meta):
    """(film time of the picture, sound, dB over the bed, pitch). Mirrors the scenes' own timings (compositions/*.html):
    each time below is the same expression the scene uses for its picture, so a re-slotted line moves its sound too.
    One vocabulary (secure-data-hub's): a soft pop = a card or part arriving or lighting; a tick = a step or a counter
    (a status dot, a check, a row); a low pop (pitch 0.8) = a refusal or an error; a whoosh = travel (the camera moving
    between zones); the riser and a soft hit = the drop. Skeleton cards, wires and fades are silent. Each effect sits
    3-6 dB over the bed and under the voice (checked by --stems), its peak one frame after its picture (place())."""
    e = []
    END = lambda k: meta[k]["end"]
    S2 = TM["s2"][0]
    # ---- s1: the two gaps light on their words, each with a grey "none" status; the riser into the drop; the icon builds
    e.append((W("v01", "publishing") - 0.05, "pop", 4, 1.0))
    e.append((W("v01", "api") + 0.05, "tick", 3, 1.0))
    e.append((W("v02", "library") - 0.05, "pop", 4, 1.06))
    e.append((W("v02", "scratch") - 0.05, "tick", 3, 1.06))
    e.append((TM["drop"], "riser", 3.5, 1.0))
    e.append((TM["drop"], "pop", 6, 1.0))                       # the soft hit: the icon's ground lands on the downbeat
    for i in range(3):                                          # its three bars rise left to right
        e.append((TM["drop"] + 0.42 + 0.12 * i, "tick", 3, 1.0 + 0.04 * i))
    e.append((W("v03", "publishes"), "pop", 4, 1.1))            # the chip "MCP server · MIT · macOS"
    # ---- s2: into the board; the spec; the dry run checks each field; the typo fails with the right names; valid
    e.append((S2 + 0.15, "whoosh_air", 4, 1.0))                 # big move 1: the title gives way to the board
    e.append((S2 + 0.35, "pop", 4, 1.0))                        # Claude Code
    e.append((W("v04", "json") - 0.05, "pop", 5, 1.0))          # the spec lights
    e.append((W("v05", "dry"), "pop", 5, 1.06))                 # validate_workbook_spec lights
    for i, w in enumerate(["every", "field", "against"]):     # the three field names looked up in turn
        e.append((W("v05", w), "tick", 3, 1.0 + 0.05 * i))
    e.append((W("v05", "typo"), "tick", 3, 0.9))                # "Status" becomes "Stauts"
    e.append((W("v05", "fails") + 0.05, "pop_low", 5, 0.8))     # the error opens, "error" status
    e.append((W("v05", "names") + 0.15, "tick", 4, 1.1))        # "Status" found in the real field list
    e.append((END("v05") + 0.4, "tick", 4, 1.0))                # fixed: the status turns "valid"
    # ---- s3: compiler, CSV, Hyper extract, checks, package
    e.append((W("v06", "compiler"), "pop", 5, 1.0))
    e.append((W("v06", "workbook"), "tick", 3, 1.0))            # ".twb"
    e.append((W("v06", "each") - 0.05, "pop", 4, 1.04))         # sites.csv
    e.append((W("v06", "hyper") - 0.05, "pop", 5, 1.08))        # Hyper extract
    e.append((W("v06", "hyper") + 0.45, "tick", 3, 1.04))       # ".hyper"
    e.append((END("v06") - 0.55, "pop", 4, 1.1))                # Checks
    e.append((END("v06") - 0.1, "pop", 4, 1.12))                # Package
    e.append((END("v06") + 0.05, "tick", 3, 1.0))               # its three real entries
    e.append((END("v06") + 0.35, "tick", 3, 1.1))               # ".twbx"
    # ---- s4: across to "On this Mac"; the real app opens, three status rows; five load errors, then five checks; the screenshots
    e.append((TM["s4"][0] + 0.3 + 0.55, "whoosh_air", 3, 1.1))  # the camera crosses the board (move at s4 + 0.3, 1.4 s)
    e.append((W("v07", "tableau") - 0.05, "pop", 5, 1.0))       # Tableau Public 2026.2.0
    for i, (w, dt) in enumerate([("app", -0.05), ("and", 0.1), ("photographs", 0.0)]):
        e.append((W("v07", w) + dt, "tick", 3, 1.0 + 0.05 * i))  # opened · no error dialog · screenshot
    e.append((W("v08", "five"), "pop", 5, 1.04))                # Five load rules
    e.append((W("v08", "load") - 0.55, "pop_low", 5, 0.8))      # the five load errors, verbatim
    for i in range(5):                                          # each turns into a check
        e.append((W("v08", "only") + 0.18 * i, "tick", 3, 1.0 + 0.04 * i))
    e.append((W("v09", "screenshot") - 0.1, "pop", 5, 1.0))     # the real dashboard screenshot
    e.append((W("v09", "untouched") + 0.1, "pop", 4, 1.05))     # the map
    e.append((W("v09", "untouched") + 0.25, "pop", 4, 1.1))     # the bar chart
    # ---- s5: across to Publishing; the save flow; the session; the public page; the guards and the real refusal
    e.append((TM["s5"][0] + 0.45, "whoosh_air", 3, 1.15))       # the camera crosses to "Publishing" (1.5 s)
    e.append((W("v10", "drives") + 0.3, "pop", 5, 1.0))         # publish_to_tableau_public
    e.append((W("v10", "save"), "tick", 3, 1.0))                # Command+Shift+S
    e.append((W("v10", "signed"), "tick", 3, 1.06))             # your signed-in session
    e.append((W("v10", "session"), "pop", 4, 1.06))             # public.tableau.com
    e.append((W("v10", "session") + 0.6, "tick", 3, 1.1))       # verified: HTTP 200
    e.append((W("v11", "never"), "pop", 5, 1.0))                # Guards
    e.append((W("v11", "replace"), "pop_low", 5, 0.8))          # refusing to publish: 'profile' is required.
    e.append((W("v11", "unless"), "tick", 3, 1.0))              # overwrite: false by default
    # ---- s6: the pull-back to the whole board; the tests card; the count to 507; the live tests
    e.append((TM["s6"][0] + 0.35, "whoosh_air", 4, 0.95))       # big move 2: out to the whole architecture
    e.append((W("v12", "507") - 0.05, "pop", 5, 1.0))           # pytest
    for i, dt in enumerate([0.05, 0.17, 0.32, 0.52, 0.85]):     # the counter (1.2 s, power2.out): ticks thin out as it settles
        e.append((W("v12", "507") + dt, "tick", 3, 1.0 + 0.04 * i))
    e.append((W("v12", "15") - 0.05, "tick", 4, 1.06))          # 15 live tests drive the real app
    # ---- s7: the end card: the icon builds again (its bars tick as on the drop), the wordmark, the two lines
    e.append((TM["s7"][0] + 0.4, "pop", 5, 1.0))
    for i in range(3):
        e.append((TM["s7"][0] + 0.85 + 0.12 * i, "tick", 3, 1.0 + 0.04 * i))
    e.append((W("v13", "tableau") - 0.05, "pop", 4, 1.06))
    e.append((W("v14", "declarative") - 0.05, "tick", 4, 1.0))
    e.append((W("v14", "compiled"), "tick", 4, 1.06))           # the URL line arrives on "compiled" (s7-end.html)
    return e


if __name__ == "__main__":
    main()
