"""Cut "Pop 07" (Grigoriy Nuzhny, Mixkit 699, Mixkit Stock Music Free License) to the Tableau Public Authoring MCP film.

    python3 -I sound/music.py     # -> assets/audio/music.wav, sound/grid.json

Andy, 2026-11-01: "calm but not too calm". Pop 07 is relaxed chillout hip-hop.

The grid, measured here with librosa (2026-11-01): exactly 90 BPM (beat-track fit 0.66669 s per beat, 11 ms residual;
librosa's 89.1 BPM is its frame quantisation). Backbeat: snare on 2 and 4, kick on 1. A bar is 8/3 s = 2.667 s and track
bar n starts at n * 8/3 s (kick onsets measured at 66.667, 69.335, 72.000, 77.332, 114.665 s). The chords run in a
two-bar cycle: odd bars Dm -> Gm ("A"), even bars Cm/Eb -> F ("B"), so every joint keeps A after B.

Structure (RMS and band energy per bar):
  bars  0-20   groove A (bars 9-10, 13-14, 17-20 lighter; 11-12, 15-16 fuller bass)
  bars 21-23   the breakdown: keys only, no sub, no drums (-18.8 dB against -12.5 dB)
  bar  24      a pickup: the chord re-enters on the one, kick and bass only from beat 2.5 (65.0 s)
  bars 25-42   groove B (busier hats; 33-34, 37-38, 41-42 lighter; 35-36, 39-40 fuller)
  bars 43-44   the outro: keys and pads thin out, bass and drums stay
  bars 45-48   the track's own fade (-21, -26, -29, -43 dB)

The edit (joins on bar lines, 12 ms crossfades). Film bar lines fall on n * 8/3 s throughout:
  film  0.000-8.000   track  56.000-64.000  bars 21-23: the breakdown under the hook
  film  8.000-53.333  track  69.333-114.667 bars 26-42: the DROP. The groove enters on a downbeat on "Tableau"; the
                                            pickup bar 24 and bar 25 are skipped (B after A, so the chords still run)
  film 53.333-58.667  track 109.333-114.667 bars 41-42 again: four light bars before the outro, as the track itself
                                            does before its breakdown (bars 17-20); the seam sits under the overview
                                            whoosh
  film 58.667-67.500  track 114.667-123.500 bars 43-46: the outro under the end card, then the track's own fade,
                                            and a 2.5 s fade on the last bars
"""
import json, subprocess
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TRACK = ROOT / "sound/track.mp3"
SR, B0, BAR = 48000, 0.0, 8 / 3
BPM = 90
tb = lambda n: B0 + n * BAR          # track bar n
fb = lambda n: n * BAR               # film bar n
SEGMENTS = [(fb(0), tb(21)), (fb(3), tb(26)), (fb(20), tb(41))]   # (film start, track start)
DROP, OUTRO = fb(3), fb(22)
FILM_END = 67.5
FADE = 2.5
XF = 0.012


def main():
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(TRACK), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    track = np.frombuffer(raw, np.float32).reshape(-1, 2).T.astype(np.float64)
    n = int(round(FILM_END * SR))
    out = np.zeros((2, n))
    x = int(XF * SR); ramp = np.linspace(0, 1, x)
    for k, (f0s, t0s) in enumerate(SEGMENTS):
        f0 = int(round(f0s * SR)); f1 = int(round(SEGMENTS[k + 1][0] * SR)) if k + 1 < len(SEGMENTS) else n
        t0 = int(round(t0s * SR))
        seg = track[:, t0: t0 + (f1 - f0)]
        seg = np.pad(seg, ((0, 0), (0, (f1 - f0) - seg.shape[1])))
        if k > 0:
            out[:, f0 - x: f0] = out[:, f0 - x: f0] * (1 - ramp) + track[:, t0 - x: t0] * ramp
        out[:, f0:f1] = seg
    fi = int(0.3 * SR); out[:, :fi] *= np.linspace(0, 1, fi)
    fo = int(FADE * SR); out[:, -fo:] *= np.linspace(1, 0, fo) ** 1.5
    import soundfile as sf
    (ROOT / "assets/audio").mkdir(parents=True, exist_ok=True)
    sf.write(ROOT / "assets/audio/music.wav", out.T.astype(np.float32), SR)
    r3 = lambda v: round(v, 3)
    grid = {"track": "Pop 07 (Grigoriy Nuzhny, Mixkit 699)", "bpm": BPM, "beat": r3(60 / BPM), "bar": r3(BAR),
            "drop": r3(DROP), "end_card": r3(OUTRO), "track_ending": r3(OUTRO), "fade_out": [r3(FILM_END - FADE), FILM_END],
            "duration": FILM_END, "film_bars": [r3(fb(i)) for i in range(int(FILM_END / BAR) + 1)],
            "segments": [[r3(a), r3(b)] for a, b in SEGMENTS],
            "segment_notes": ["track bars 21-23, the breakdown, under the hook",
                              "track bar 26 on the drop: the groove on a downbeat (bars 24-25 skipped)",
                              "track bars 41-42 repeated (light), then the outro (bar 43) on the end card and the fade"]}
    (ROOT / "sound/grid.json").write_text(json.dumps(grid, indent=1))
    print(f"music.wav {FILM_END} s; drop {DROP:.3f}, outro/end card {OUTRO:.3f}, fade {FILM_END - FADE}-{FILM_END}")


if __name__ == "__main__":
    main()
