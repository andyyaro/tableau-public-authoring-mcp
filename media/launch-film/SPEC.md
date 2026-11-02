# Tableau Public Authoring MCP launch film: SPEC

```text
GOAL:    a data or developer-tools person understands, in about a minute, how this MCP server gets around Tableau
         Public's two gaps (no publishing API, no library that builds a workbook from scratch): a JSON spec is
         checked, compiled with a Hyper extract, opened and photographed in the real Tableau Public app, and
         published through Tableau's own save flow behind real guards. Proof: 507 tests that pass with no Tableau
         installed. Every artifact on screen is the project's own (its screenshots, its spec, its error text).
OUTPUT:  HyperFrames 0.8.173, 1920 x 1080, 30 fps, 67.5 s (sound stage, 2026-11-01; must stay 55-70 s).
         renders/tableau-mcp-v1.mp4. Plumbing copied from secure-data-hub (build.py, index.html with W() cues on
         window.VO, compositions/*.html, narration/pick.py, sound/music.py, sound/mix.py, sound/sfx-src/,
         assets/vendor/gsap.min.js, hyperframes.json, package.json). Board and subtitle layer modelled on the
         CERFODES source (arch-diagram.html camera, index.html subtitle pill, build-icons.mjs + hig-icons.js).
SOUND:   (sound stage 2026-11-01: sound/music.py, sound/mix.py, sound/grid.json, sound/timing.json are the truth)
         Music "Pop 07" (Grigoriy Nuzhny, Mixkit 699, Mixkit Stock Music Free License), relaxed chillout hip-hop.
         Grid measured with librosa and checked on kick onsets: exactly 90 BPM, beat 0.667 s, bar 8/3 = 2.667 s,
         track bar n at n x 8/3 s (onsets at 66.667, 69.335, 72.000, 114.665 s), snare on 2 and 4. Chords in a
         two-bar cycle (odd bars Dm-Gm, even bars Cm/Eb-F): every joint keeps an even bar after an odd one.
         Structure: groove A bars 0-20; breakdown bars 21-23 (56.0-64.0 s: keys only, no sub, no drums); bar 24 a
         pickup (chord on the one, kick and bass only from 65.0 s); groove B bars 25-42 (light pairs 33-34, 37-38,
         41-42; fuller pairs 35-36, 39-40); outro bars 43-44 (keys thin out); the track's own fade bars 45-48.
         The edit, on bar lines with 12 ms crossfades (film bar lines are n x 8/3 s for the whole film):
           film  0.000- 8.000  track  56.000- 64.000  breakdown under the hook
           film  8.000-53.333  track  69.333-114.667  the DROP at 8.000: groove B bar 26 on a downbeat, exactly on
                                                    the "T" of "Tableau" (v03); bars 24-25 skipped
           film 53.333-58.667  track 109.333-114.667  the light pair 41-42 again (four light bars, as the track does
                                                    before its own breakdown); the seam sits under the overview whoosh
           film 58.667-67.500  track 114.667-123.500  the outro under the end card, the track's own fade, and a
                                                    2.5 s fade at the end (65.0-67.5)
         Music under the picture: 8.0-26.7 full groove (title, spec, build); 26.7-32.0 light; 32.0-37.3 fuller bass
         (the five load rules); 37.3-42.7 light (screenshots); 42.7-48.0 fuller (publish); 48.0-58.7 light (guards,
         overview, tests); 58.7 outro (end card).
         Voice Kokoro af_heart, all 14 lines the 1.0-speed take, every transcript matching the script word for word
         (whisper large-v3-turbo). "API" is now plain "API" in lines-tts.json (the spaced "A P I" came out as
         "a PI"); "M C P", "C S V", "Jason" and the spelled numbers stay. Lines (film s): v01 0.70-3.09,
         v02 3.70-6.90, v03 7.94-12.18, v04 13.40-15.07, v05 15.50-20.39, v06 21.85-28.31, v07 29.80-33.89,
         v08 34.35-37.38, v09 37.80-41.86, v10 43.80-47.67, v11 48.15-52.62, v12 53.90-58.63, v13 59.85-61.79,
         v14 62.35-65.40. Breaths inside a scene 0.42-0.61 s; the longer gaps are the camera's.
         Levels (measured by mix.py over the spans she speaks and the gaps): mix -16.0 LUFS integrated, true peak
         -1.9 dBTP, LRA 2.8 LU; speech -15.5 LUFS; the bed 9.4 dB under the voice between lines and 13.0 dB under
         while she speaks (the duck is 4.5 dB nominal, 3.6 dB measured with its 450 ms release).
         Soft effects from sound/sfx-src (copied from secure-data-hub) with ONE vocabulary (finish stage
         2026-11-01, 69 effects in sfx_events()): a soft pop (mixkit-2357) = a card or part arriving or lighting;
         a tick (mixkit-1120) = a step or a counter (status dots, the three field checks, the five rules turning
         green, the count to 507, the icon's bars); a low pop (mixkit-3005, "pop_low", always pitch 0.8) = an
         error or a refusal (the typo's error on "fails", the five load errors arriving, the 'profile' refusal);
         whoosh_air (mixkit-1492) = the camera travelling: +4 into the board (12.82) and out to the overview
         (53.68), +3 across to "On this Mac" (30.18) and to "Publishing" (43.78); a riser (mixkit-2408, 1.2 s
         fade-in) and a soft hit (pop +6) only on the drop. Skeletons, wires and fades are silent; no typing.
         Each effect's level is set against the bed under it: its loudest 100 ms (K-weighted) sits 3-6 dB over
         the ducked bed's K-weighted RMS over 1.2 s around its peak, so the quiet hook and the full groove get
         the same distance; peak one frame after its picture. Checked from mix.py --stems: 2.5-6.0 dB over the
         bed, every effect at least 4 dB under the voice where she speaks. Levels after the effects: mix -16.0
         LUFS, true peak -1.9 dBTP, LRA 2.8 LU; the bed alone 9.6 dB under the speech between lines and 13.3 dB
         under while she speaks (duck 3.7 dB measured).
LOOK:    Reference: Andy's CERFODES architecture film (cerfodes-architecture-en-1080p.mp4), built in HIG
         Native, Andy's unofficial web design system that follows Apple's HIG. Taken from it, exactly:
           ground   grouped background #f2f2f7; zones are big rounded areas in fill-quaternary rgba(116,116,128,.08)
                    (radius 26) with a bold zone label and a grey secondary label beside it
           cards    white #ffffff, radius 16-22, no shadow, no border: a 44 px rounded-square tile (radius 11) in
                    a system colour holding a white 24 px HIG line glyph, a bold title (22-23 px / 600) and a grey
                    secondary line (18 px, label-secondary #68686d for legibility); status = dot + word
                    ("● valid", "● opened"); small capsule chips in fill-tertiary for code words
           skeleton placeholder cards arrive faint (opacity .5) and fill in on the word that names them
           wires    thin grey arrows (system-gray #8e8e93, 2.5 px, small triangular heads) with 17 px grey edge
                    labels; dashed only for the publish path (public, irreversible)
           board    ONE big 1920 x 1080 world the camera glides and zooms across (close shots at zoom >= 1.55),
                    then pulls back to the whole architecture at zoom 1.0, where secondary lines fold away and only
                    titles, status words, the legend and the tests number stay
           titles   section title "Bold title" (30 px / 700) + small grey subtitle at the top left
           captions burned-in subtitles in a dark rounded pill at the bottom (rgba(0,0,0,.74), radius 18,
                    38/47 px, weight 500, max 42 chars x 2 lines); the band y >= 936 is never drawn on (mask the
                    board below 916-936 px like CERFODES #a-fade)
           end      the project's mark, the wordmark, two short lines with icons
         Type: the system face loaded exactly as CERFODES does:
           @font-face { font-family:"HostUI"; src: local("SF Pro"), local("SF Pro Display"), local(".SF NS"); }
           --font-ui: "HostUI", -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
         (/System/Library/Fonts/SFNS.ttf is present on this Mac.) NEVER --font-mono, never SFNSMono, never the
         brand's Martian Mono. Code words (validate_workbook_spec, .twbx, confirm_publish, the JSON spec, the
         error strings) are set in HostUI, sentence case, in chips or plain lines. No caps labels are planned; if
         one is added it is Montserrat SemiBold caps, +0.12-0.14em.
         Colours: HIG Native light tokens (as in CERFODES index.html) plus system-purple #cb30e0 and
         system-pink #ff2d55 from tokens.json. Brand (docs/assets/brand): aubergine #2A0E33, pink #FF4FA3,
         peach #FFD9C2, blush #FFF0F6 appear ONLY inside the app icon / mark (assets/brand/icon-rounded.svg,
         mark-color.svg), the way CERFODES keeps its blue-gold icon. The wordmark is set in HostUI Bold
         ("Tableau Public Authoring MCP", the README's H1), label-primary: the brand lockup is NOT used because
         its wordmark is Martian Mono (a monospace face, banned on screen).
         Legend (overview only): green "runs without Tableau", indigo "needs Tableau Public on this Mac",
         orange "public and irreversible".
MOTION:  calm, CERFODES values: cards pop (opacity 0 -> 1, y 18 -> 0, scale .96 -> 1, 0.6 s, back.out(1.5));
         placeholders fade to .5 then "light" on their word (content rises 10 px, a 1.035 scale breath); status
         dots slide in 8 px 0.45 s after their card; wires draw by stroke-dashoffset (0.45 s, power2.inOut) and the
         head appears at the end; camera moves 1.1-1.5 s power2.inOut, with a slow 'none' drift while holding.
         Cues come from the voice's own word times (W("v05","typo") etc. on window.VO). Exits fade at about half
         the entrance. No shake, no bounce beyond back.out(1.5), no blur trails.
SHOTS:   (film windows from sound/timing.json, window.TM; cue words come from window.VO, so a re-slotted line re-times
         the picture by itself. Key word times: "typo" 18.58, "right names" 19.66, "compiler" 21.99, "CSV" 24.53,
         "hyper" 25.77, "requires" 27.55, "opens" 30.08, "photographs" 33.04, "Five" 34.35, "screenshot" 38.08,
         "untouched" 40.34, "save" 45.46, "signed" 46.74, "credentials" 48.95, "unless" 51.55, "507" 53.90,
         "15" 56.96, v13 59.85, v14 62.35)
         s1 hook+title 0-12.667 Section title "Tableau Public" + grey "for code". Two white cards, centred, side by
                                side, each with a gray tile and a gray "● none" status:
                                  [globe] "Publishing API" / "the REST API covers Server and Cloud only"   (v01)
                                  [doc]   "Build from scratch" / "the Document API can't create files from
                                          scratch" (v02)
                                On the drop (8.0 s, "Tableau" of v03) the cards fade, whoosh_air + soft pop: the
                                app icon (icon-rounded.svg, 220 px) builds: the two pink braces draw, the three
                                peach bars rise left to right; the wordmark "Tableau Public Authoring MCP" (HostUI
                                700, about 84 px) rises; a capsule chip "MCP server · MIT · macOS" lands on
                                "publishes".
         s2 spec       12.667-21.333 Into the board (whoosh_air). Camera zoom ~1.75 on the left column "Who asks":
                                card [text.alignleft, gray] "Claude Code" / "MCP client · over stdio"; a wire
                                labelled "stdio" into the zone "tableau-public-authoring" / "MCP server · 10 tools"
                                (faint). On "JSON" (v04) the spec window lights: a white card titled "Site Map" /
                                "workbook spec · JSON" holding the README's map worksheet, one key per line, in
                                HostUI 19 px: "template": "map" · "data_source": "sites" · "detail": ["Site Name"] ·
                                "color": "Status" · "size": Sum of "Annual Sessions" · "title": "Candidate sites".
                                A "sites.csv" card under it: "12 rows · synthetic fixture". On "dry run" (v05) the
                                card [text.page.badge.magnifyingglass, teal] "validate_workbook_spec" / "dry run ·
                                writes nothing" lights. On "typo": the spec's "Status" turns to "Stauts" in
                                system-red, low pop, and a white error card slides under the validator with the
                                real text: "specification error: worksheets[0].color: field 'Stauts' does not exist
                                in data source 'sites'." and a row of chips "Available:" ... "Site Name" "State"
                                "Status" (Status highlighted). On "right names": the typo reverts to "Status", the
                                error card folds away, tick, the validator's status "● valid".
         s3 build      21.333-29.333 Camera glides into the zone (zoom ~1.6). Placeholders for four cards, each lights on
                                its word: [gearshape, indigo] "Compiler" / "ElementTree XML, never string splicing"
                                chip ".twb" ("compiler"); [square.3.layers.3d.top.filled, purple] "Hyper extract" /
                                "tableauhyperapi" chip ".hyper" ("CSV"/"Hyper"); a grey edge label on its wire:
                                "required: Error Code 3C242D89 without it"; [archivebox, blue] "Package" /
                                "ZIP-slip guarded" chip ".twbx"; [checkmark.circle, green] "Checks" / "no machine
                                paths · structure valid" status "● warnings: none" ("requires"). Under the package
                                card, the real build_workbook entries as three chips: "Demo_Map.twb"
                                "Data/sites/sites.hyper" "Data/sites/sites.csv".
         s4 real app   29.333-43.333 Camera to the zone "On this Mac" (zoom ~1.7). [square.grid.2x2, blue] "Tableau
                                Public 2026.2.0" / "opened by validate_in_tableau_public": three status rows tick in:
                                "● opened" "● no error dialog" "● screenshot" ("photographs"). On v08 a card
                                [exclamationmark.triangle, orange] "Five load rules" / "found only by opening the
                                file in Tableau" lists Tableau's five real error strings, one per row, each turning
                                from a red x to a green check (tick per row, one low pop at the first):
                                  missing required attribute 'dim-percentage'
                                  no declaration found for element 'object-graph'
                                  element 'filter' is not allowed for content model
                                  element 'panes' is not allowed for content model
                                  attribute 'object-id' is not declared for element 'extract'
                                On v09 the camera glides across the real screenshots, each in a white rounded
                                window card with a grey caption: demo_dashboard.png (zoom ~2.2, "Dashboard · two
                                generated sheets, 1200 x 800"), then demo_map.png ("Symbol map · 12 marks"); the
                                bar chart (demo_bar.png, "Bar chart · colour and labels") is passed on the way and
                                seen whole at the overview. One shared caption chip: "generated from a spec ·
                                untouched in Tableau Public 2026.2.0 · synthetic 12-row data". Images uncropped
                                (keeps the Mapbox/OpenStreetMap credit).
         s5 publish    43.333-53.333 Camera to the column "Outside" (zoom ~1.7). Dashed wire from the Tableau card to
                                [square.and.arrow.up, pink] "publish_to_tableau_public" / "Save to Tableau Public
                                As..." chip "Command+Shift+S" ("save flow") status "● your signed-in session".
                                On v11 a card [lock, gray] "Guards" with chips "confirm_publish: true" "profile"
                                "overwrite: false" and a line "credentials: never read, typed or stored"; the real
                                refusal slides in under it as a white card with a red x and low pop: "refusing to
                                publish: confirm_publish must be true." ("unless told to" turns the chip
                                "confirm_publish: true" green, tick). Then [globe, teal] "public.tableau.com" /
                                "public and irreversible" with "verify_published_workbook · HTTP 200" (the
                                2026-07-27 verified run).
         s6 overview   53.333-59.4 (runs on under the end card from 58.667 while the board fades) whoosh_air; the
                                camera pulls back to the whole board at zoom 1.0, held still. The
           + proof                header "How Tableau Public Authoring MCP works" and the legend fade in; secondary
                                lines, chips and error cards fold away. The Tests card at the bottom right lights on
                                v12: [checkmark.circle.fill, green] "pytest" / "commit d77186f", a big "507" (64 px,
                                counts up 0 -> 507 over ~1.2 s, ticks) "pass without Tableau installed", then a
                                second line "● 15 live tests drive the real app" (indigo dot) and a small line
                                ".twb byte-identical on rebuild".
         s7 end        58.667-67.5 The board fades; the app icon builds again (braces draw, bars rise) 200 px;
                                "Tableau Public Authoring MCP" (HostUI 700, ~84 px) on v13; two lines with icons on
                                v14: [doc] "Declarative specs, compiled into Tableau workbooks." and [globe]
                                "github.com/andyyaro/tableau-public-authoring-mcp". v13 and v14 are "onscreen"
                                lines: no caption pill for them. Hold ~2 s, fade with the music.
AS BUILT (build stage, 2026-11-01; where the picture differs from SHOTS above):
         hosts: s1-hook, s2-board (s2..s6, one camera), s2-titles (the screen-space section titles and the
         overview legend, same window), s7-end; subtitles are clips in index.html written by build.py.
         Hook: grey subtitle "two constraints"; card 2's status "● not supported". Titles per beat: "Describe",
         "Build", "Open it in Tableau Public", "Real output" (carries the shared caption line), "Publish".
         Column D is labelled "Publishing": public.tableau.com sits on top, publish_to_tableau_public under it, then
         Guards (chips "confirm_publish: true" "profile", status "● overwrite: false by default"); the refusal is
         the real publish_without_profile text ("refusing to publish: 'profile' is required. Without it ..."),
         because the confirm_publish refusal is not what the narration ("won't replace a live workbook") names.
         The five load rules card is transient (gone before the screenshots); the screenshots sit as 1 + 2
         (dashboard zoom 1.95, then the map and bar pair at 2.6). Package chips are the three build entries,
         status ".twbx". Camera: s2 C(436,370,1.5), s3 (436,500/646,1.6), s4 (1154,322,1.75), s5 (1560,304,1.7)
         then (1560,577,1.45), s6 (960,500,1.0); dimmed columns at 0.22.
REVIEW (2026-11-01, REVIEW.md): the validator's error folds away by its own height as the status turns valid
         (END v05 + 0.3); Checks and Package light just before v06 ends and the move to "On this Mac" starts at
         s4 + 0.3, so the package's real entries settle at close range; the Five load rules skeleton arrives with the zone;
         the s4 subtitle is "loaded into the app itself, then photographed"; the Package wire dims for the 2.6 close-up;
         the end card's second tick is on "compiled".
OBJECTS: real only. Spec = README "The spec behind the map" worksheet (shown as the README prints it, never called
         the whole input of the screenshot). Error text, build entries and refusal text = research/real-responses.json
         (the server's own call_tool() output at d77186f). Five load errors = docs/VALIDATION_REPORT.md layer 3.
         Screenshots = assets/artifacts/demo_*.png (docs/images, untouched). Tool names = server.py (10 tools).
         Tests = pytest at d77186f on this Mac with no Tableau Public installed: 507 passed, 15 deselected (live
         tier). Icon = assets/brand/icon-rounded.svg (unchanged). Glyphs = HIG Native hig-icons.js via
         build-icons.mjs (copy both from the CERFODES source), only: text.alignleft, doc, text.page.badge.
         magnifyingglass, gearshape, square.3.layers.3d.top.filled, archivebox, checkmark.circle, checkmark.circle.
         fill, xmark.circle.fill, square.grid.2x2, exclamationmark.triangle, photo, square.and.arrow.up, lock, globe,
         checkmark. Every claim is in FACTS.md.
BANNED:  any monospace (mono|Mono|monospace|Courier|Menlo|Consolas|ui-monospace|SFNSMono|Martian), including for
         the JSON, the hash and the error strings; the brand lockup files (Martian Mono wordmark); em dashes and
         en-dash separators on screen; the Huly look; drop shadows on content; a row of three feature cards (the
         hook has two cards, the proof one card; the screenshots are visited one at a time, not lined up as a
         trio); the logo docked in a corner; screen shake; a flood of messages; Tableau's own logo drawn as a
         glyph (it appears only inside the real screenshots); a Claude or Anthropic logo; any invented Tableau UI;
         any figure not in FACTS.md (no user counts, no stars, no "faster"); the stale "419 tests" in Andy's project notes.
QA:      2.0, 5.5, 9.4, 11.8, 15.0, 17.2, 19.3, 20.9, 24.8, 28.0, 31.5, 33.6, 36.8, 39.4, 42.4, 46.0, 50.0,
         52.6, 55.6, 58.2, 60.8, 65.0, 67.0 (from the sound stage's windows: one frame per beat, plus the typo, the
         valid state, the five rules, the dashboard close-up, the refusal, the overview and the end card). At each: no text under the caption band, nothing clipped at the
         frame edge at its zoom, smallest on-screen text >= 22 px after zoom, the grep for mono returns nothing.
```
