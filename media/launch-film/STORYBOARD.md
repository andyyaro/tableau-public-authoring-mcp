# Tableau Public Authoring MCP launch film: storyboard and build

67.5 s, 1920 × 1080, 30 fps (2,025 frames). H.264 with AAC at 256 kb/s; measured on the MP4:
-16.0 LUFS integrated, true peak -1.8 dBTP, loudness range 2.8 LU. Made against `main` at
`d77186f`. Every claim in it and its source is in [FACTS.md](FACTS.md); the brief, with every
shot and timing, is [SPEC.md](SPEC.md). The server's own replies shown on screen are in
[research/real-responses.json](research/real-responses.json).

## What is real and what is rebuilt

- **Real outputs, captured from the code:** the server's own `call_tool()` replies at `d77186f`,
  run offline with `osascript`, `open` and `screencapture` made to fail so nothing could reach the
  desktop. On screen: the dry run's error for the typo `Stauts`, with its list of field names; the
  build's three package entries (`Demo_Map.twb`, `Data/sites/sites.hyper`, `Data/sites/sites.csv`)
  and no warnings; the publish refusal ("refusing to publish: 'profile' is required. ...").
- **Measured in a clone of the repository:** `pytest -q` gives 507 passed and 15 deselected (the
  live tier in `tests/live`, which drives the visible app), with no Tableau Public installed. Two
  builds of the same spec give the same `.twb` SHA-256; the `.twbx` differs, and the film does not
  claim otherwise.
- **The repository's own records,** because they need Tableau Public, which was not installed and
  not opened for the film: the three screenshots (`docs/images/`, untouched), the five load errors
  (`docs/VALIDATION_REPORT.md`, layer 3) and the one verified publish (HTTP 200, 2026-07-27).
- **Drawn in HTML:** the architecture board itself, its cards and wires. The spec on it is the
  README's "spec behind the map", as the README prints it. The film never calls that snippet the
  map screenshot's whole input, because the screenshot also shows `City` on Label and a subtitle.
- **Left out on purpose:** the stale "419 tests", star counts and the decision-matrix score.
  [FACTS.md](FACTS.md) says why for each.

## The film

| Time (s) | Scene | Narration | What you see |
|---|---|---|---|
| 0–12.7 | Hook and title | "Tableau Public has no publishing API. And no official library can build workbooks from scratch. Tableau Public Authoring MCP builds and publishes them anyway." | "Tableau Public", "two constraints". Two white cards: "Publishing API", "the REST API covers Server and Cloud only", "● none"; "Build from scratch", "the Document API can't create files from scratch", "● not supported". On the drop at 8.0 s, on the "T" of "Tableau", the cards fade and the app icon builds: the two pink braces draw and the three peach bars rise. The name rises under it; the chip "MCP server · MIT · macOS" lands on "publishes". |
| 12.7–21.3 | Describe | "Describe a workbook in JSON. A dry run checks every field against the data, so a typo fails with the right names." | Into the board. "Who asks": Claude Code, "MCP client · over stdio", wired into the server, "MCP server · 10 tools". The workbook spec fills in, then `validate_workbook_spec` ("dry run · writes nothing"). On "typo", "Status" turns to "Stauts" in red and the real error slides in: "specification error: worksheets[0].color: field 'Stauts' does not exist in data source 'sites'.", with the available fields as chips and "Status" marked. On "right names" the typo reverts, the error folds away and the status reads "● valid". |
| 21.3–29.3 | Build | "The compiler writes the workbook, and turns each CSV into the Hyper extract Tableau Public requires." | "Build", "a .twb, a Hyper extract, one .twbx". Compiler ("ElementTree XML, never string splicing", `.twb`); `sites.csv` ("12 rows · synthetic fixture") into Hyper extract ("tableauhyperapi, one per CSV", `.hyper`, "Error Code 3C242D89 without it"); Checks ("no machine paths · structure valid", "warnings: none"); Package ("ZIP-slip guarded") with the three real entries and `.twbx`. |
| 29.3–43.3 | Open it in Tableau Public, real output | "Then it opens the file in the real Tableau Public app, and photographs it. Five of Tableau's load rules only showed up that way. Every screenshot here is a generated workbook, untouched in Tableau." | "On this Mac": Tableau Public 2026.2.0, "opened by validate_in_tableau_public", then "● opened", "● no error dialog", "● screenshot". "Five load rules", "found only by opening the file in Tableau": Tableau's five real error strings, each turning from a red cross to a green check. Then "Real output": the dashboard screenshot close up ("Dashboard · two generated sheets, 1200 x 800"), then the map ("Symbol map · 12 marks") and the bar chart ("Bar chart · colour and labels"). |
| 43.3–53.3 | Publish | "Publishing drives Tableau's own save flow, in your signed-in session. It never reads credentials, and won't replace a live workbook unless told to." | "Publish", "Tableau's own save flow, behind guards". A dashed wire to `publish_to_tableau_public` ("Save to Tableau Public As...", "Command+Shift+S", "● your signed-in session") and on to public.tableau.com ("public and irreversible", `verify_published_workbook`, "verified: HTTP 200"). Guards: "credentials: never read, typed or stored", `confirm_publish: true`, `profile`, "● overwrite: false by default", and the real refusal for a missing `profile`. |
| 53.3–59.4 | The whole board | "507 tests pass without Tableau. 15 more drive the real app." | The camera pulls back to the whole architecture: "How Tableau Public Authoring MCP works", with a legend (runs without Tableau, needs Tableau Public on this Mac, public and irreversible). The pytest card ("commit d77186f") counts up to 507, "pass without Tableau installed", then "● 15 live tests drive the real app" and ".twb byte-identical on rebuild". |
| 58.7–67.5 | End card | "Tableau Public Authoring MCP. Declarative specs, compiled into Tableau workbooks." | The board fades and the icon builds again; the name; "Declarative specs, compiled into Tableau workbooks." (the brand sheet's tagline) and github.com/andyyaro/tableau-public-authoring-mcp, on the music's own outro and fade. These two lines are on screen, so they are not burned in; they are in the captions file. |

## Look

- **Style:** an architecture film, as the project has no interface of its own. It follows Andy's
  CERFODES architecture film, in HIG Native (Andy's unofficial web design system after Apple's
  HIG): one big board on the grouped background #f2f2f7 that the camera glides and zooms across,
  white cards with no shadows, line glyphs in system-colour tiles, status as a dot and a word,
  skeleton cards that fill in on the word that names them, thin grey wires with small edge labels,
  and burned-in subtitles in a dark pill.
- **Brand:** the app icon is the repository's `docs/assets/brand/icons/icon-rounded.svg`,
  unchanged; its colours (aubergine #2A0E33, pink #FF4FA3, peach #FFD9C2) appear only in the icon.
  The brand's lockup is not used, because its wordmark is Martian Mono, a monospace face; the name
  is set in the system face instead. There is no Tableau, Claude or Apple logo; Tableau's own
  interface appears only inside the real screenshots.
- **Type:** SF Pro throughout, loaded with `local()` as "HostUI", as the CERFODES source does it.
  No monospace anywhere on screen, the JSON, the commit hash and the error strings included, and no
  em dashes. Icons: the HIG Native line glyphs (`scripts/vendor/hig-icons.js`, written into
  `index.html` by `scripts/build-icons.mjs`).
- **Motion:** calm: cards pop in over 0.6 s, wires draw, camera moves of 1.1 to 1.5 s with a slow
  drift while holding. Every cue is a word time from the narration (`window.VO`), so a re-voiced
  line re-times the picture by itself.

## Sound

- **Voice:** Kokoro-82M, voice af_heart, the 1.0-speed take of all 14 lines (140 words), each
  checked word for word with Whisper. "MCP", "CSV", "JSON" and the numbers are spelled for the
  voice in `narration/lines-tts.json` ("M C P", "C S V", "Jason", "Five hundred and seven");
  `narration/words.json` keeps the script's spellings so the cues find their words.
- **Music:** "Pop 07" by Grigoriy Nuzhny (Mixkit 699), relaxed chillout hip-hop at exactly 90 BPM,
  cut on its bar lines by `sound/music.py`:
  - the track's keys-only breakdown under the hook;
  - the drop at 8.000 s, a groove downbeat exactly on the "T" of "Tableau", as the icon builds;
  - the groove under the board, with its light pair of bars repeated under the pull-back to the
    overview;
  - the track's own outro under the end card (58.667 s), then a 2.5 s fade to 67.5 s.
- **Effects:** 69 soft Mixkit interface sounds from five: a soft pop for a card or part arriving,
  a tick for a step or a counter, a low pop for an error or a refusal, an air whoosh for the camera
  travelling, and a riser and a soft hit only on the drop. Skeleton cards, wires and fades make no
  sound. Each effect peaks one frame after its picture and sits 3 to 6 dB over the music under it.
  The list is in [assets/audio/SOURCE.md](assets/audio/SOURCE.md).
- **Levels:** speech set to -16 LUFS; the music 9.6 dB under it between lines and ducked to 13.3 dB
  under while she speaks; master -16.0 LUFS, true peak -1.8 dBTP.

## Build

Get the inputs first: `tools/fetch_vendor.sh` for GSAP, then the music and effects listed in
[assets/audio/SOURCE.md](assets/audio/SOURCE.md). The Python steps need numpy, soundfile, scipy,
librosa and mlx-whisper (`<voice-venv>`); voicing the lines needs Kokoro-82M. The render needs a
Mac, for SF Pro.

```sh
tools/fetch_vendor.sh
# Voice each line of narration/lines-tts.json with Kokoro-82M (af_heart) at speeds 1.0 and 1.06,
# as narration/takes/<id>.<k>.wav
<voice-venv>/bin/python -I narration/pick.py takes     # best take per line, words.json
<voice-venv>/bin/python -I sound/music.py              # assets/audio/music.wav, sound/grid.json
<voice-venv>/bin/python -I sound/mix.py                # mix.wav, vo.wav, assets/vo.js, assets/timing.js
python3 -I build.py                                    # scene windows, subtitles, the .vtt
node scripts/build-icons.mjs .                         # only when the glyph list changes
npx --yes hyperframes@0.8.173 lint && npx --yes hyperframes@0.8.173 check
npx --yes hyperframes@0.8.173 render -o renders/raw.mp4 --fps 30
ffmpeg -y -i renders/raw.mp4 -i assets/audio/mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 256k \
  -shortest -movflags +faststart renders/tableau-mcp-v1.mp4
```

The ffmpeg step puts the exact mix back on the picture rather than keeping the renderer's own
re-encode of it. `sound/mix.py --stems <dir>` writes the voice, the music and the effects apart,
for checking levels. Each effect in `sfx_events()` (`sound/mix.py`) uses the same word-time
formula as its picture in `compositions/*.html`; if a scene's cue changes, change it there too.

## The README preview

`docs/assets/readme/tableau-mcp-in-action.webp` is 13.2–29.2 s of the film: the spec, the dry
run catching the typo with the real field names and turning valid, then the build down to the
package's three entries. 1200 × 676, 15 fps, lossy WebP at quality 90, looping, 5.9 MB.

Every frame is a keyframe (`-kmax 1`). With the usual partial frames, lossy WebP skips changes
too small to see one frame at a time, so slow fades and camera moves left faint grey patches and
bands on the flat board that lasted until the next keyframe (3.5 MB). A keyframe every 4 frames
still showed them while the camera moved (4.1 MB).

```sh
mkdir -p preview
ffmpeg -ss 13.2 -t 16 -i renders/tableau-mcp-v1.mp4 -vf fps=15,scale=1200:676:flags=lanczos preview/f%03d.png
img2webp -loop 0 -kmax 1 -lossy -q 90 -m 6 -d 67 preview/f*.png -o ../../docs/assets/readme/tableau-mcp-in-action.webp
```
