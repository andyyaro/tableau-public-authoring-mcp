# Third-party sounds, pictures and type in the film

The music and sound effects are in the film but not in this repository. Their licences cover using
them inside a film, not handing the files on by themselves, so they are listed here instead.
Download each one again to the path shown to rebuild.

## Music

| Used as | Track | Licence | Put it at |
|---|---|---|---|
| The bed under the whole film, cut on its bar lines by `sound/music.py` | "Pop 07" by Grigoriy Nuzhny, Mixkit 699 | [Mixkit Stock Music Free License](https://mixkit.co/license/#musicFree): free in any project, no credit required, not for use in a music-only track | `sound/track.mp3` |

## Sound effects

All from Mixkit, under the [Mixkit Sound Effects Free License](https://mixkit.co/license/#sfxFree).
The names are the ones `sound/mix.py` uses (`SFX`); each file goes in `sound/sfx-src/` as
`mixkit-<id>.mp3`. The film places 69 of them, all from these five sounds.

| Name in `mix.py` | Mixkit id | What it marks |
|---|---|---|
| `pop` | 2357 | A card or part arriving or lighting up; turned up, the soft hit on the drop |
| `tick` | 1120 | A step or a counter: a status dot, a field check, a load rule turning green, the count to 507 |
| `pop_low` | 3005 | Always at pitch 0.8: an error or a refusal (the typo's error, Tableau's five load errors, the publish refusal) |
| `whoosh_air` | 1492 | The camera travelling: into the board, across to "On this Mac" and to "Publishing", out to the overview |
| `riser` | 2408 | Once: the swell into the drop |

## Voice

Kokoro-82M ([Apache-2.0](https://huggingface.co/hexgrad/Kokoro-82M)), voice af_heart, run
locally. The lines are `narration/lines-tts.json`; the audio is generated, so it is not kept.

## Type

All text is SF Pro, Apple's system font, loaded with `local()` as the "HostUI" face in
`index.html`. No font file is used or shipped, so the film renders only on a Mac. Whether SF Pro's
licence covers a published video is Andy's call, as for the CERFODES film this one follows. The
brand's wordmark typeface (Martian Mono, a monospace face) is not used in the film.

## Pictures

The three screenshots in the film are the repository's own `docs/images/demo_dashboard.png`,
`demo_map.png` and `demo_bar.png`, copied unchanged and uncropped to `assets/artifacts/` (the
same files, under this repository's MIT licence). Each is a workbook this server generated from a
spec, opened in Tableau Public 2026.2.0 and photographed untouched, on the synthetic 12-row fixture.
Tableau's own interface appears only inside them, and the map keeps its Mapbox and OpenStreetMap
credit.

The app icon is the repository's `docs/assets/brand/icons/icon-rounded.svg`, unchanged (a copy is
in `assets/brand/`); the scenes draw it inline so its braces and bars can build. The line icons are
HIG Native's (`scripts/vendor/hig-icons.js`).
