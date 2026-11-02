# Tableau Public Authoring MCP launch film

The 68-second film at the top of the [repository README](../../README.md), published at
https://andyyaro.github.io/tableau-public-authoring-mcp/film.html. It starts with Tableau
Public's two gaps: no publishing API, and no official library that builds a workbook from scratch.
Then the app icon builds on the music's drop, and the camera glides across one architecture board:
the JSON spec and the dry run, which catches a typo and names the right fields; the compiler, the
Hyper extract, the checks and the package; Tableau Public on the Mac, the five load rules that only
showed up there and the repository's three real screenshots; publishing through Tableau's own save
flow, behind guards. It pulls back to the whole board for the proof, 507 tests that pass without
Tableau and 15 more that drive the real app.

The project has no interface of its own, so the film is an architecture board, not a screen
recording. The error text, the build's package entries and the publish refusal on the board are
the server's own replies, captured offline from the code with the desktop tools made to fail.
Tableau Public was not installed or opened for the film: the screenshots, the five load errors and
the verified publish are the repository's own records.

[STORYBOARD.md](STORYBOARD.md) has the scenes, the look, the sound and every build step.
[FACTS.md](FACTS.md) has every claim in the film and where it comes from, and
[SPEC.md](SPEC.md) is the brief the film was built from: every shot, number and timing.

## What is here

| Path | What it is |
|---|---|
| `index.html`, `compositions/` | The composition (HyperFrames 0.8.173, GSAP): the hook and title, the architecture board, its section titles and legend, and the end card, plus the burned-in subtitles and the icon sprite in `index.html` |
| `assets/board-parts.js`, `assets/kit.js` | The board's cards, the spec, the five load errors, the screenshot windows and the wires, and the shared motion helpers; the board's timeline is `compositions/s2-board.html` |
| `assets/vo.js`, `assets/timing.js` | The narration's word times (`window.VO`) and the scene windows and drop (`window.TM`), written by `sound/mix.py`; the scenes find their cues in them |
| `assets/artifacts/` | The three screenshots, the same files as `docs/images/` |
| `assets/brand/icon-rounded.svg` | The app icon, the same file as `docs/assets/brand/icons/`; the scenes draw it inline |
| `build.py` | Writes the scene windows and subtitles into the composition, and the captions file |
| `sound/` | The music edit (`music.py`), the mix (`mix.py`: narration, music and 69 effects, each cued to its picture), the bar grid (`grid.json`) and the timing (`timing.json`) |
| `narration/` | The script (`lines.json`), the script as voiced (`lines-tts.json`), `pick.py`, which chooses the best take of each line and times its words, and the word times (`words.json`) |
| `research/real-responses.json` | The server's own replies shown on the board: the dry run, the typo's error, the build, both publish refusals and the two builds' hashes |
| `SPEC.md` | The brief: goal, sound, look, motion, every shot and the board's parts |
| `FACTS.md` | Every line of narration and every on-screen claim, with its source |
| `scripts/` | The HIG Native line icons and the script that writes them into `index.html` |
| `tools/fetch_vendor.sh` | Fetches GSAP at the pinned version and checks the file's SHA-256 |
| `deploy/film.html`, `deploy/index.html` | The watch page, and a redirect to it from the site's root |
| `assets/audio/SOURCE.md` | Every third-party sound, picture and typeface in the film, with its licence and where it goes |
| `hyperframes.json`, `package.json` | The HyperFrames project settings and the render scripts |

## What is not here, and why

The working folder for the film is about 63 MB. This folder keeps the source and leaves out
everything that is generated or that its licence does not let us hand on by itself:

- **Generated:** the narration takes and the chosen lines, the music edit, the mix, the voice on
  its own, the render and its captions file. The build steps make them again.
- **Screen recordings:** there are none. Nothing in the film was recorded from a screen; the board
  is drawn in HTML and the screenshots are the repository's own.
- **Third-party media:** the music ("Pop 07" by Grigoriy Nuzhny, Mixkit) and five Mixkit sound
  effects. [assets/audio/SOURCE.md](assets/audio/SOURCE.md) lists each one with its licence and the
  path it goes to.
- **Libraries and fonts:** GSAP 3.14.2 is fetched by `tools/fetch_vendor.sh`. All text is SF Pro,
  the Mac's system font, loaded with `local()`, so no font file is used or shipped and the film
  renders only on a Mac.

## Publishing

The MP4, its captions and its poster are assets of the
[`film-v1` release](https://github.com/andyyaro/tableau-public-authoring-mcp/releases/tag/film-v1),
so the 13.8 MB film is not in the repository's history. The
[film page workflow](../../.github/workflows/film.yml) puts them on GitHub Pages with
`deploy/film.html`, `deploy/index.html`, the mark and the favicon from `docs/assets/brand/`. It
runs when anything in `deploy/` changes on `main`. After replacing a release asset, run it by hand:

```sh
gh release upload film-v1 tableau-mcp-launch.mp4 --clobber
gh workflow run film.yml
```

## Credits

Narration: Kokoro-82M (Apache-2.0), voice af_heart. Music: "Pop 07" by Grigoriy Nuzhny (Mixkit).
Sound effects: Mixkit. Type: SF Pro (Apple's system font). Icons: HIG Native line glyphs. The app
icon and the screenshots are the project's own (`docs/assets/brand/`, `docs/images/`). The film
names Tableau Public, the app the server drives, and Tableau's Hyper API (`tableauhyperapi`);
Tableau's own interface appears only inside the screenshots.
