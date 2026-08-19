# Dashboard XML Forensics - reverse-engineering `<dashboards>` from real fixtures

**Why this document exists.** The canonical reference workbook for this project
(`REFERENCE_WORKBOOK_ANALYSIS.md`, `dashboard_count: 0`) contains no dashboards, so the
compiler has never had a verified dashboard structure to copy. This document
supplies one, derived from downloaded published workbooks rather than from
memory or documentation.

**Method.** Pure file analysis. No Tableau GUI was driven, opened, or activated.
Every `.twbx` was downloaded through the `tableau-public` reader MCP, unpacked
with `unzip`, and parsed with `xml.etree.ElementTree`. Every claim below is
labelled **[V]** verified-from-fixture or **[I]** inferred - read the labels.

---

## 1. Fixture provenance

The three workbooks named in the task brief were all **refused**: author
`dashboard.temple` has `allowDataAccess: false` on every one of them, and
`download_workbook_twbx` correctly declines before transferring bytes.

| Workbook | Author | `allowDataAccess` | Outcome |
|---|---|---|---|
| `BlankBasicBusinessDashboardTemplate` | dashboard.temple | `false` | refused - `"The workbook author has disabled data downloads"` |
| `BlankPremiumBusinessDashboardTemplates` | dashboard.temple | `false` | refused (not attempted after flag check) |
| `BasicBusinessDashboardTemplate` | dashboard.temple | `false` | refused (not attempted after flag check) |

Fallback via `search_visualizations` produced three downloadable fixtures.

### PRIMARY fixture - used for the skeleton

| Field | Value |
|---|---|
| Title | **Simple dashboard** |
| Author | Sebastian Wareluk (`sebastian.wareluk`) |
| Workbook name | `Simpledashboard_15814156889310` |
| URL | <https://public.tableau.com/app/profile/sebastian.wareluk/viz/Simpledashboard_15814156889310/Dashboard1> |
| `.twbx` SHA-256 | `3855d56c1a2396bd0d697c5098844d86cadb5d3d8f7ad4b930e460573438a278` |
| `.twbx` size | 380,317 bytes |
| Downloaded | 2026-07-27 |
| Inner `.twb` | `Simple dashboard.twb`, 73,001 bytes |
| Doc `version` | **`18.1`** |
| `source-build` | `2019.4.3 (20194.20.0125.0835)` |
| Contents | 3 worksheets, 1 dashboard, 17 zones |

**Why this one is primary:** its document `version` is `18.1` - *identical* to the
`DOC_VERSION` this compiler already pins (`compiler/workbook.py:22`). Tableau's
loader content model keys off the document version, not the writing build, so an
18.1 dashboard is the correct structural target even though the build that wrote
it (2019.4.3) is older than our target runtime (2026.2.0).

### CORROBORATING fixtures - used to separate invariants from version drift

| Workbook | Author | SHA-256 | Doc ver | Build | Zones |
|---|---|---|---|---|---|
| `simpledashboard_0` | shailendra kumar | `71050c7aa27c8c70cf035b10bcdc9626a455e95934fe280b5fd7eb18d109ae5a` | `10.4` | `2023.1.0 (20231.23.0505.1444)` | 27 |
| `SimpleDashboard` | Ushka | `cb940bb729789e31bbd739f9ca609ba06afaa3a96a7e6890186d6eabcfcd4fc4` | `8.3` | *(absent)* | 9 |

The 8.3 fixture is the most minimal dashboard obtainable and is quoted below as
a lower bound on required structure. The 10.4 fixture is written by build
2023.1.0 - the closest available to our 2026.2.0 target - and is the evidence
that no new required elements appeared between 2019 and 2023.

> **Provenance caveat [V].** `simpledashboard` (author `prittam`) and
> `SimpleDashboard` (author `ushka`) were downloaded to the same cache directory
> on a case-insensitive macOS filesystem and collapsed to one file - both paths
> hash to `cb940bb7…`. The surviving file is whichever landed second. The 8.3
> content is therefore attributed to one of those two authors with low
> confidence. This does not affect any structural finding; the 8.3 file is used
> only for corroboration, never as the sole source of a claim.

---

## 2. Where `<dashboards>` sits in the workbook

**[V]** All three fixtures agree exactly. `<dashboards>` is a direct child of
`<workbook>`, positioned **between `<worksheets>` and `<windows>`**:

| Fixture | Top-level element order |
|---|---|
| 18.1 | `document-format-change-manifest, repository-location, preferences, datasources, mapsources, actions, worksheets, **dashboards**, windows` |
| 10.4 | `repository-location, preferences, style, datasources, shared-views, worksheets, **dashboards**, windows` |
| 8.3 | `repository-location, preferences, datasources, worksheets, **dashboards**, windows, thumbnails` |

**[V]** `<dashboards>` itself carries **no attributes** (`{}` in all fixtures).

This slots cleanly into the compiler's existing `build()`, which currently emits
`preferences → datasources → worksheets → windows`.

---

## 3. `<dashboard>` element - attributes and child order

**[V]** `<dashboard>` has exactly one attribute in all fixtures: `name`. No
`id`, no `caption`, no `version`.

**[V]** Observed child sequences:

| Fixture | Children of `<dashboard>`, in file order |
|---|---|
| 18.1 | `repository-location, layout-options, style, size, datasources, datasource-dependencies, zones, devicelayouts, simple-id` |
| 10.4 | `layout-options, repository-location, style, size, datasources, datasource-dependencies, datasource-dependencies, zones` |
| 8.3 | `repository-location, style, size, zones` |

**[V] The invariant spine**, after deleting `repository-location` and
`simple-id` (published-only, see §8) is identical across all three versions:

```
layout-options? , style , size , datasources? , datasource-dependencies* , zones , devicelayouts?
```

**[V] Ordering is not fully rigid.** `layout-options` precedes
`repository-location` in the 10.4 fixture and follows it in the 18.1 fixture.
Since we omit `repository-location` entirely, this ambiguity is moot - but it is
evidence that Tableau's content model tolerates at least some reordering around
that element. **[I]** I did *not* verify that `style`/`size`/`zones` may be
reordered, and the compiler must not try: emit them in the order above.

**[V]** `<style/>` is present and **empty** in the 18.1 and 8.3 fixtures. In the
10.4 fixture it carries one rule:
`<style><style-rule element="dash-title"><format attr="border-style" value="solid"/></style-rule></style>`.
An empty `<style/>` is therefore sufficient. **[I]** Whether `<style>` is
*mandatory* is unverified - it is present in 3/3 fixtures, so emit it.

**[V]** `<datasources>` / `<datasource-dependencies>` inside `<dashboard>` are
present only when the dashboard hosts a zone that references a *field*
(`filter`, `highlighter`, `color`, `paramctrl`). The 8.3 fixture, whose zones are
worksheets + a text box only, has neither. Their internal shape is identical to
the worksheet-level ones the compiler already builds:

```xml
<datasources>
  <datasource caption="Orders (Sample - Superstore)" name="federated.1rzz…" />
</datasources>
<datasource-dependencies datasource="federated.1rzz…">
  <column datatype="date" name="[Order Date]" role="dimension" type="ordinal" />
  <column-instance column="[Order Date]" derivation="Year" name="[yr:Order Date:ok]"
                   pivot="key" type="ordinal" />
</datasource-dependencies>
```

---

## 4. The zone tree

### 4.1 Coordinate space - **0..100000 normalised grid, absolute, per-dashboard**

This is the single most important finding for a compiler, so the evidence is
laid out in full.

**Evidence 1 [V] - the root zone is always exactly the full grid.** In every
dashboard in every fixture, spanning doc versions 8.3, 10.4 and 18.1, the
outermost zone is:

```
<zone h="100000" id="…" type="layout-basic" w="100000" x="0" y="0">
```

and no zone anywhere has any of `x`, `y`, `w`, `h` exceeding 100000.

**Evidence 2 [V] - children carry ABSOLUTE coordinates, not parent-relative.**
The horizontal `layout-flow` container `id=20` in the 18.1 fixture sits at
`x=468 w=99064`. Its six children tile it exactly:

| child id | `x` | `w` | `x+w` |
|---|---:|---:|---:|
| 19 (title) | 468 | 16560 | 17028 |
| 13 (filter) | 17028 | 16500 | 33528 |
| 15 (highlighter) | 33528 | 16501 | 50029 |
| 26 (empty) | 50029 | 16501 | 66530 |
| 21 (empty) | 66530 | 16501 | 83031 |
| 22 (color) | 83031 | 16501 | 99532 |

Sum of child widths = 99064 = parent width, and the first child's `x` equals the
*parent's* `x` (468), not 0. If coordinates were parent-relative the first child
would be at `x=0`. They are absolute in the dashboard's own grid.

**Evidence 3 [V] - the units are not pixels, proven by axis asymmetry.** The
root zone declares a single uniform `<format attr="margin" value="8"/>`. That one
8-pixel margin appears in the grid as **468 horizontally** and **885
vertically**. A pixel unit cannot render one margin as two different numbers.
Solving `8 / (n/100000)` gives an implied canvas of 1709.4 × 904.0 px - a
plausible maximized window, and consistent with this dashboard's
`<size sizing-mode="automatic"/>`. The grid is normalised independently on each
axis against the dashboard's current extent.

**Evidence 4 [V] - cross-check on a fixed-size dashboard.** The 8.3 fixture
declares `<size maxwidth="1100" minwidth="1100" maxheight="700" minheight="700"/>`
and lays out two side-by-side worksheets at `w=49819` and `w=49817`
(`x=0` and `x=49819`). `49819/100000 × 1100 px = 548.0 px` - precisely half of
the 1100 px canvas less the gutter. The normalised value maps onto the declared
pixel size exactly as predicted.

**Conclusion [V]:** `x`, `y`, `w`, `h` are integers in a `0..100000` grid,
absolute within the dashboard, with the origin at the top-left. Siblings inside
a `layout-flow` must tile their parent's extent with no gap and no overlap.

### 4.2 Zone nesting

**[V]** `<zones>` contains exactly **one** root `<zone type="layout-basic">` at
full extent. Containers nest arbitrarily deep; leaf zones are content.

**[V]** Child-element order *inside* a `<zone>`, from a census of all zones in
all fixtures (0 counter-examples):

```
zone*  ,  formatted-text?  ,  layout-cache?  ,  zone-style?
```

`zone-style` is **last in 100% of the 40 zones that have one**. Nested `<zone>`
children always precede it.

### 4.3 Zone types observed

**[V]** Full census of the `type` attribute across all fixtures:

| `type` | Meaning | Notable attributes |
|---|---|---|
| *(absent)* | **a worksheet zone** | `name` = worksheet name; optional `show-title` |
| `layout-basic` | plain container (the root, and grouping wrappers) | - |
| `layout-flow` | horizontal/vertical stack | `param="horz"` \| `param="vert"`, optional `layout-strategy-id="distribute-evenly"` |
| `title` | the dashboard title card | - |
| `text` | free text box (8.3 fixture) | child `<formatted-text>` |
| `filter` | quick-filter card | `name`, `param`, `mode`, `show-all`, `show-filter-state` |
| `highlighter` | highlight-action card | `name`, `param` |
| `color` | colour legend | `name`, `param`, `pane-specification-id` |
| `paramctrl` | parameter control | `param="[Parameters].[Parameter 1]"`, `mode`, `custom-title` |
| `bitmap` | image | `param="Image/2.PNG"`, `is-centered`, `is-scaled` |
| `empty` | blank spacer | - |

> **[V] `type-v2` DOES NOT EXIST in any fixture.** `grep -c 'type-v2'` returns
> **0** for all four downloaded `.twb` files, across doc versions 8.3, 10.4 and
> 18.1 and builds up to 2023.1.0. The task brief asked me to document
> `type-v2` values; the honest answer is that I found none and have no evidence
> the attribute is used at document version 18.1. **The compiler must emit
> `type`, not `type-v2`.** See RISKS §9.1.

### 4.4 How a zone references a worksheet - **the discriminator is absence of `type`**

**[V]** A worksheet is placed by a zone whose `name` attribute is the worksheet's
`name`, and which has **no `type` attribute at all**:

```xml
<zone h="92146" id="3" name="Total sales sub cat" w="49532" x="50000" y="6969">
  <zone-style>…</zone-style>
</zone>
```

**[V] Critical subtlety:** `name` is *also* used by `filter`, `highlighter` and
`color` zones - but there it names the worksheet the card *belongs to*, not a
worksheet to render. In the 18.1 fixture all six `name`-bearing zones carry a
valid worksheet name, yet only the three with no `type` are worksheet views:

| zone id | `type` | `name` | role |
|---|---|---|---|
| 3 | *(none)* | `Total sales sub cat` | **renders the worksheet** |
| 12 | *(none)* | `Map` | **renders the worksheet** |
| 10 | *(none)* | `Ilość klientów w miastach` | **renders the worksheet** |
| 13 | `filter` | `Map` | filter card *for* Map |
| 15 | `highlighter` | `Map` | highlighter *for* Map |
| 22 | `color` | `Total sales sub cat` | colour legend *for* that sheet |

**[V]** There is **no** `<zone worksheet="…">` attribute and no id-based
reference. The link is by worksheet **name string**, which means a dashboard
zone breaks silently if a worksheet is renamed.

**[V]** `show-title="false"` on a worksheet zone hides that sheet's title inside
the dashboard. Default (attribute absent, or `"true"` in the 8.3 fixture) shows it.

### 4.5 `id` - small sequential integers, NOT hashes

**[V]** Zone ids are small positive integers, unique within a dashboard, and
sparse/non-contiguous (Tableau reuses a monotonic counter and leaves gaps as
zones are deleted):

| dashboard | ids |
|---|---|
| 18.1 `Dashboard 1` | 3,4,5,7,9,10,11,12,13,15,16,18,19,20,21,22,26 |
| 10.4 `Sample DAshboard ` | 1..5,8,9,11..14,16..21,25..34 |
| 8.3 `Sales Overview 2013` | 1,2,3,5,6,8,9,11,12 |

**[V]** Ids are **not** ordered by tree position - the root zone is `id=4` in the
18.1 fixture while its descendants are 3, 5, 7. Contiguity and ordering are
therefore *not* required.

**[V]** In the 18.1 fixture the `<devicelayout>` block **reuses** the main
layout's ids (19, 13, 15, 12, 3, 22, 10) and adds two new ones (29, 30) for its
own containers - so ids are scoped to the whole `<dashboard>`, shared across
layouts.

> **Implication for this codebase:** `compiler/ids.py::stable_id` produces
> 28-character base-36 strings. Those are **wrong** for zone ids. A simple
> deterministic ascending counter over a deterministic tree walk satisfies both
> Tableau's format and the project's determinism requirement.

### 4.6 `layout-cache` and `zone-style`

**[V]** `<layout-cache/>` is an empty element carrying sizing hints. Attributes
observed: `minheight`, `maxheight`, `has-max-size-h`, `type-h`, `type-w`
(values `scalable` / `fixed`). It appears on only 4 of 53 zones. **[I]** Its
name and its absence from most zones strongly suggest it is a cache Tableau
recomputes; I did **not** verify it is optional. Safest course: omit it.

**[V]** `<zone-style>` holds `<format attr= value=/>` children. Attribute
vocabulary observed, with counts:
`border-color` (40), `border-style` (40), `border-width` (40), `margin` (40),
`padding` (7), `background-color` (4).

**[V]** The near-universal quartet is:

```xml
<zone-style>
  <format attr="border-color" value="#000000" />
  <format attr="border-style" value="none" />
  <format attr="border-width" value="0" />
  <format attr="margin" value="4" />   <!-- 8 on the root zone -->
</zone-style>
```

### 4.7 Layout containers

**[V]** A horizontal or vertical container is
`<zone type="layout-flow" param="horz|vert" …>`. `param` is the *only* thing
that distinguishes the two directions. Optional
`layout-strategy-id="distribute-evenly"` (seen once) makes children share space
equally.

**[V]** `type="layout-basic"` wraps a *floating*/absolutely-positioned group and
is always the root. The 18.1 fixture alternates
`layout-basic → layout-flow → layout-basic → layout-flow …` down the tree; the
extra `layout-basic` wrappers appear to be artefacts of interactive editing.
**[I]** A generator does not need to reproduce that alternation - the 8.3
fixture nests `layout-flow` directly inside `layout-flow` - but this is inferred
from a different document version and is a real risk (§9.2).

**[V]** `fixed-size="<px>"` + `is-fixed="true"` pins a zone to an absolute pixel
size along the container's flow axis while siblings absorb the remainder. Note
`fixed-size` **is in pixels**, unlike `x/y/w/h`.

### 4.8 Filter cards, legends and highlighters

**[V]** Verbatim from the 18.1 fixture:

```xml
<!-- quick filter -->
<zone fixed-size="195" h="6084" id="13" is-fixed="true" mode="dropdown" name="Map"
      param="[federated.1rzz…].[yr:Order Date:ok]"
      show-all="false" show-filter-state="false" type="filter" w="16500" x="17028" y="885">
  <zone-style>…</zone-style>
</zone>

<!-- colour legend -->
<zone h="6084" id="22" name="Total sales sub cat" pane-specification-id="0"
      param="[federated.1rzz…].[sum:Profit:qk]" type="color" w="16501" x="83031" y="885">
```

**[V]** `param` is the **fully-qualified column-instance reference** -
`[<datasource-name>].[<derivation>:<Field>:<typesuffix>]` - byte-identical in
form to what `workbook.py::_qualified(_instance_name(...))` already produces for
worksheet shelves and for the `param` on `<card type="filter">`.

**[V]** `mode` values seen: `dropdown`, `checkdropdown`, `datetime` (paramctrl).
The existing worksheet card code already emits `mode="checkdropdown"`.

**[V]** Any dashboard containing such a zone also carries `<datasources>` +
`<datasource-dependencies>` declaring the referenced column and column-instance
(§3). A filter zone whose column is not declared there is unresolvable.

---

## 5. Dashboard sizing

**[V]** Sizing is a `<size>` element, never attributes on `<dashboard>`. Three
distinct forms observed:

| Form | Fixture | Meaning |
|---|---|---|
| `<size sizing-mode="automatic" />` | 18.1 | fits the browser/window; no min/max |
| `<size maxheight="1400" maxwidth="1100" minheight="1400" minwidth="1100" sizing-mode="fixed" />` | 10.4 | **fixed canvas**; min == max on both axes |
| `<size maxheight="700" maxwidth="1100" minheight="700" minwidth="1100" />` | 8.3 | fixed canvas, `sizing-mode` **absent** (pre-18.1 style) |
| `<size maxheight="1150" minheight="1150" sizing-mode="vscroll" />` | 18.1 devicelayout | vertical-scroll; height pinned, width free |

**[V]** For a fixed canvas, `minwidth == maxwidth` and `minheight == maxheight`;
values are **pixels**. `sizing-mode="fixed"` is the modern spelling and is what a
generator targeting 18.1 should emit alongside the four bounds.

**[I]** `sizing-mode` values `automatic`, `fixed`, `vscroll` are the three I
observed. Tableau's UI also offers "Range", whose serialisation I did not
capture - do not emit anything outside the three verified values.

---

## 6. Dashboard title

**[V]** A dashboard title requires **two cooperating pieces**, and this is a
common way to get it wrong:

1. The **text**, in `<layout-options>` directly under `<dashboard>`:

```xml
<layout-options>
  <title>
    <formatted-text>
      <run>Simple dashboard</run>
    </formatted-text>
  </title>
</layout-options>
```

2. A **zone to display it**, of `type="title"`, placed in the zone tree:

```xml
<zone fixed-size="254" h="6084" id="19" is-fixed="true" type="title"
      w="16560" x="468" y="885"> … </zone>
```

**[V]** Omitting the `type="title"` zone means the title text exists in the file
but occupies no space on the canvas. The 8.3 fixture does the opposite - it has
**no** `<layout-options>` and instead renders its heading with a
`type="text"` zone holding its own `<formatted-text>`:

```xml
<zone forceUpdate="true" h="6139" id="12" type="text" w="99636" x="0" y="0">
  <formatted-text>
    <run fontalignment="1" fontname="Open Sans" fontsize="16">Sales Overview 2013</run>
  </formatted-text>
</zone>
```

**[V]** The `<run>` element and its attributes (`fontsize`, `fontcolor`,
`fontname`, `fontalignment`) are the same vocabulary
`workbook.py::_build_worksheet` already emits for worksheet titles.

---

## 7. Registration in `<windows>`

**[V]** Every dashboard needs a `<window class="dashboard">` sibling to the
worksheet windows. Verbatim, 18.1:

```xml
<window class="dashboard" maximized="true" name="Dashboard 1">
  <viewpoints>
    <viewpoint name="Ilość klientów w miastach"><zoom type="entire-view" /></viewpoint>
    <viewpoint name="Map">
      <zoom type="entire-view" />
      <highlight field="[federated.1rzz…].[none:State:nk]" type="highlight">
        <bucket-selection />
      </highlight>
    </viewpoint>
    <viewpoint name="Total sales sub cat" />
  </viewpoints>
  <active id="-1" />
  <simple-id uuid="{93EED6B5-…}" />
</window>
```

**[V] How it differs from `<window class="worksheet">`:**

| | `class="worksheet"` | `class="dashboard"` |
|---|---|---|
| children | `cards` (+ `viewpoint`, `simple-id`) | `viewpoints`, `active` (+ `simple-id`) |
| `<cards>` | **required** - the shelf/legend furniture | **absent** - a dashboard has no shelves |
| per-sheet state | one `<viewpoint>` | one `<viewpoints>` wrapper containing a `<viewpoint name="…">` per contained worksheet |
| `<active>` | absent | `<active id="-1" />` |

**[V]** The dashboard window carries `maximized="true"`. In the 10.4 fixture the
dashboard window is listed **first**, before the worksheet windows, and every
worksheet window carries `hidden="true"` - that is how a workbook publishes with
only the dashboard tab visible. In the 18.1 fixture the dashboard window is last
and no window is hidden.

**[V]** The 8.3 fixture uses an entirely different shape -
`<window class="dashboard"><zones><zone name="…"><viewpoint>…` - which is
obsolete at 18.1. Do not copy it.

**[I]** I did not verify whether `<viewpoints>` is *required* or may be empty.
Emitting one bare `<viewpoint name="X"/>` per contained worksheet matches the
fixture and is the conservative choice.

---

## 8. Published-only elements - must NOT be emitted

The project already knows about `repository-location`, `simple-id`,
`object-graph`, and `extract/@object-id`. Dashboards add more.

| Element | Where it appears | Verdict |
|---|---|---|
| `repository-location` | on `<workbook>` **and on every `<dashboard>`** | **[V]** omit - publish-server metadata, contains a public.tableau.com URL and numeric repo id |
| `simple-id` | on `<dashboard>`, on each `<window>`, on each `<worksheet>` | **[V]** omit - a `{GUID}`; also non-deterministic, which would break `test_determinism` |
| `devicelayouts` / `devicelayout` | on `<dashboard>` (18.1) | **[V]** carries `auto-generated="true"` - Tableau regenerates phone layouts itself. Omit. |
| `document-format-change-manifest` | root (18.1) | **[V]** upgrade bookkeeping (`AutoCreateAndUpdateDSDPhoneLayouts`, `WindowsPersistSimpleIdentifiers`, …). Omit. |
| `thumbnails` | root (8.3) | **[V]** base64 PNG previews the server generates. Omit. |
| `shared-views` | root (10.4) | **[V]** server-side artefact. Omit. |
| `mapsources` | root (18.1) | **[V]** not dashboard-related; the EV reference has it too. Omit. |
| `layout-cache` | on `<zone>` | **[I]** *probably* a recomputed cache; unverified. Omit - see §9.4. |
| `forceUpdate` | on 8.3 `type="text"` zone | **[I]** looks like a dirty-flag. Omit. |
| `<actions>` | root, when the dashboard has filter actions | **[V]** a real user-authored feature, **not** publish metadata - but out of scope for v0.1. Omit and document as unsupported. |

---

## 9. Minimum viable `<dashboard>` - annotated skeleton

Two worksheets stacked vertically under a title, on a fixed 1200×800 canvas.
Every element below is present in the primary 18.1 fixture; published-only
elements are stripped.

```xml
<!-- direct child of <workbook>, AFTER <worksheets>, BEFORE <windows> -->
<dashboards>
  <dashboard name="{{DASHBOARD_NAME}}">

    <!-- 1. title text. Omit this whole block if there is no title. -->
    <layout-options>
      <title>
        <formatted-text>
          <run>{{DASHBOARD_TITLE}}</run>
        </formatted-text>
      </title>
    </layout-options>

    <!-- 2. always emit, empty is fine -->
    <style />

    <!-- 3. fixed canvas: min == max on both axes, values in PIXELS -->
    <size maxheight="{{HEIGHT_PX}}" maxwidth="{{WIDTH_PX}}"
          minheight="{{HEIGHT_PX}}" minwidth="{{WIDTH_PX}}"
          sizing-mode="fixed" />
    <!-- or, for an auto-fitting dashboard:  <size sizing-mode="automatic" /> -->

    <!-- 4. ONLY if a filter/legend/highlighter zone is present below.
            Omit both elements entirely for a worksheets-and-title dashboard. -->
    <datasources>
      <datasource caption="{{DS_CAPTION}}" name="{{DS_NAME}}" />
    </datasources>
    <datasource-dependencies datasource="{{DS_NAME}}">
      <column datatype="string" name="[{{FIELD}}]" role="dimension" type="nominal" />
      <column-instance column="[{{FIELD}}]" derivation="None"
                       name="[none:{{FIELD}}:nk]" pivot="key" type="nominal" />
    </datasource-dependencies>

    <!-- 5. exactly one root zone at full grid extent -->
    <zones>
      <zone h="100000" id="1" type="layout-basic" w="100000" x="0" y="0">

        <!-- vertical stack filling the root -->
        <zone h="100000" id="2" param="vert" type="layout-flow" w="100000" x="0" y="0">

          <!-- title CARD. Without this the title text renders nowhere. -->
          <zone h="6000" id="3" type="title" w="100000" x="0" y="0">
            <zone-style>
              <format attr="border-color" value="#000000" />
              <format attr="border-style" value="none" />
              <format attr="border-width" value="0" />
              <format attr="margin" value="4" />
            </zone-style>
          </zone>

          <!-- WORKSHEET ZONE: name = worksheet name, and NO type attribute -->
          <zone h="47000" id="4" name="{{WORKSHEET_NAME_1}}" w="100000" x="0" y="6000">
            <zone-style>
              <format attr="border-color" value="#000000" />
              <format attr="border-style" value="none" />
              <format attr="border-width" value="0" />
              <format attr="margin" value="4" />
            </zone-style>
          </zone>

          <zone h="47000" id="5" name="{{WORKSHEET_NAME_2}}" w="100000" x="0" y="53000">
            <zone-style>
              <format attr="border-color" value="#000000" />
              <format attr="border-style" value="none" />
              <format attr="border-width" value="0" />
              <format attr="margin" value="4" />
            </zone-style>
          </zone>

        </zone>
        <!-- zone-style is ALWAYS the last child of a zone -->
        <zone-style>
          <format attr="border-color" value="#000000" />
          <format attr="border-style" value="none" />
          <format attr="border-width" value="0" />
          <format attr="margin" value="8" />
        </zone-style>
      </zone>
    </zones>

  </dashboard>
</dashboards>
```

And in `<windows>`, alongside the existing `class="worksheet"` entries:

```xml
<window class="dashboard" maximized="true" name="{{DASHBOARD_NAME}}">
  <viewpoints>
    <viewpoint name="{{WORKSHEET_NAME_1}}" />
    <viewpoint name="{{WORKSHEET_NAME_2}}" />
  </viewpoints>
  <active id="-1" />
</window>
```

**Tiling invariant the generator must maintain:** children of the `vert`
container must satisfy `sum(h) == parent.h` and each child's `y` must equal the
previous child's `y + h`, starting at `parent.y`. Same for `w`/`x` under `horz`.
In the skeleton: `6000 + 47000 + 47000 = 100000`, and `y` runs 0 → 6000 → 53000.

---

## 10. Element / attribute classification

Legend: **IB** invariant boilerplate · **VS** version-specific · **GID** generated
id · **UC** user content · **PS** position/size · **OMIT** unsupported-must-omit.

| Element / attribute | Class | Notes |
|---|---|---|
| `workbook/dashboards` | IB | no attributes; between `worksheets` and `windows` |
| `dashboard/@name` | UC | must match the `<window class="dashboard">/@name` and be unique |
| `dashboard/layout-options/title/formatted-text/run` | UC | title text; `run` text is escaped by ElementTree |
| `run/@fontsize`, `@fontcolor`, `@fontname`, `@fontalignment` | UC | optional styling |
| `dashboard/style` | IB | emit empty |
| `dashboard/style/style-rule` | UC | only seen at 10.4; not needed |
| `dashboard/size/@sizing-mode` | VS | `fixed` \| `automatic` \| `vscroll`; absent pre-18.1 |
| `dashboard/size/@minwidth/@maxwidth/@minheight/@maxheight` | PS | **pixels**; min == max for a fixed canvas |
| `dashboard/datasources/datasource/@name` | GID | reuse `datasource_name()` output |
| `dashboard/datasources/datasource/@caption` | UC | the data source id |
| `dashboard/datasource-dependencies/@datasource` | GID | same value as above |
| `…/column/@datatype/@name/@role/@type` | IB | identical shape to the worksheet-level emitter |
| `…/column-instance/@column/@derivation/@name/@pivot/@type` | IB | `@pivot="key"` constant |
| `dashboard/zones` | IB | exactly one root `<zone>` child |
| `zone/@id` | GID | **small unique integer**, NOT a SHA-derived base-36 string |
| `zone/@x`, `@y`, `@w`, `@h` | PS | **0..100000 normalised, absolute**; siblings must tile exactly |
| `zone/@type` (`layout-basic`) | IB | root zone only |
| `zone/@type` (`layout-flow`) + `@param` | IB | `param="horz"` \| `"vert"` |
| `zone/@layout-strategy-id` | IB | optional `"distribute-evenly"` |
| `zone` with `@name` and **no** `@type` | UC | **the worksheet reference**, by name string |
| `zone/@show-title` | UC | `"false"` hides the worksheet's own title |
| `zone/@type="title"` | IB | the dashboard-title card |
| `zone/@type="text"` + `formatted-text` | UC | free text box |
| `zone/@type="filter"` + `@name` `@param` `@mode` `@show-all` `@show-filter-state` | UC | quick-filter card; `param` = qualified column-instance |
| `zone/@type="color"` + `@name` `@param` `@pane-specification-id` | UC | colour legend |
| `zone/@type="highlighter"` + `@name` `@param` | UC | highlight card |
| `zone/@type="paramctrl"` + `@param` `@mode` `@custom-title` | UC | parameter control - no parameter support in v0.1 |
| `zone/@type="bitmap"` + `@param` `@is-centered` `@is-scaled` | UC | image - requires packaging an `Image/` entry |
| `zone/@type="empty"` | IB | spacer |
| `zone/@fixed-size` + `@is-fixed` | PS | **pixels**, along the flow axis only |
| `zone/zone-style/format/@attr/@value` | IB | always the last child; `border-*` + `margin` quartet |
| `zone/layout-cache/*` | OMIT | probably a recomputed cache - unverified, do not emit |
| `zone/@forceUpdate` | OMIT | 8.3-only dirty flag |
| `windows/window/@class="dashboard"` `@name` `@maximized` | IB | `maximized="true"` |
| `window/viewpoints/viewpoint/@name` | IB | one per contained worksheet |
| `window/viewpoints/viewpoint/zoom/@type` | IB | `"entire-view"`; optional |
| `window/viewpoints/viewpoint/highlight` | OMIT | highlight-action state; not authored in v0.1 |
| `window/active/@id` | IB | constant `"-1"` |
| `window/@hidden="true"` on worksheet windows | UC | how the 10.4 fixture shows only the dashboard tab |
| `dashboard/repository-location` | OMIT | published-only; leaks a public.tableau.com URL |
| `dashboard/simple-id`, `window/simple-id` | OMIT | published-only GUID; also breaks determinism |
| `dashboard/devicelayouts` | OMIT | `auto-generated="true"`; Tableau regenerates |
| `workbook/document-format-change-manifest` | OMIT | upgrade bookkeeping |
| `workbook/thumbnails`, `workbook/shared-views` | OMIT | server artefacts |
| `workbook/actions` | OMIT | real feature, but out of scope for v0.1 |
| `zone/@type-v2` | OMIT | **not found in any fixture at any doc version** |

---

## 11. Implementation plan

Ordered, and shaped to the existing architecture: `ElementTree` nodes only (no
string building), deterministic ids, layer-1 semantic validation in
`models/spec.py`, layer-2 structural validation in `validation/structure.py`.

### Step 1 - `compiler/ids.py`: add an integer zone-id allocator

`stable_id()` is unsuitable (base-36, 28 chars). Add a tiny deterministic
counter class rather than a hash:

```python
class ZoneIdAllocator:
    """Sequential zone ids. Tableau uses small unique integers, not hashes."""
    def __init__(self) -> None:
        self._next = 1
    def take(self) -> str:
        val = self._next
        self._next += 1
        return str(val)
```

One allocator **per dashboard** (ids are dashboard-scoped, §4.5). Determinism
comes from the deterministic tree walk, and `test_determinism` still passes.

### Step 2 - `models/spec.py`: dashboard spec model

Add dataclasses beside `Worksheet`:

```python
@dataclass
class DashboardItem:
    kind: str                 # "worksheet" | "filter" | "legend" | "blank"
    worksheet: str | None = None
    field: str | None = None  # for filter/legend
    show_title: bool = True

@dataclass
class Dashboard:
    name: str
    items: list[DashboardItem]
    direction: str = "vertical"   # "vertical" | "horizontal"
    title: str | None = None
    width: int = 1200             # pixels
    height: int = 800
    sizing_mode: str = "fixed"    # "fixed" | "automatic"
```

Add `dashboards: list[Dashboard]` to `WorkbookSpec` (default `[]`, so no
existing caller breaks).

### Step 3 - `models/spec.py`: replace the hard rejection

`parse_spec` currently does (lines 384-389):

```python
dashboards = raw.get("dashboards") or []
_require(not dashboards, "dashboards are not supported in v0.1 …")
```

Replace with a parse loop that validates, at minimum:

- `name` via `_check_name`, unique across dashboards **and** disjoint from
  worksheet names (both land in `<windows>` keyed by name);
- every `item.worksheet` exists in `seen_ws` - the zone→worksheet link is by
  name string and fails silently otherwise (§4.4);
- `direction in ("vertical", "horizontal")`, `sizing_mode in ("fixed", "automatic")`;
- `width`/`height` positive integers within a sane range when `sizing_mode == "fixed"`;
- at least one item, and for a `filter`/`legend` item, that `field` exists in the
  referenced worksheet's data source;
- **all worksheets referenced by one dashboard resolve to data sources whose
  `<datasource>`/`<datasource-dependencies>` the dashboard can declare** -
  needed for filter/legend zones (§3).

Also add `SUPPORTED_DASHBOARD_ITEMS` next to `SUPPORTED_TEMPLATES` and keep
`docs/architecture/CAPABILITY_BOUNDARY.md` in lockstep, per the comment at
`spec.py:23`.

### Step 4 - `compiler/workbook.py`: a normalised layout helper

Pure function, no XML - easy to unit-test:

```python
GRID = 100000

def _tile(count: int, total: int, offset: int) -> list[tuple[int, int]]:
    """Split `total` grid units into `count` contiguous spans starting at `offset`.
    The last span absorbs the rounding remainder so spans tile EXACTLY (§4.1)."""
    span = total // count
    out, pos = [], offset
    for i in range(count):
        size = total - (pos - offset) if i == count - 1 else span
        out.append((pos, size))
        pos += size
    return out
```

The "last span absorbs the remainder" rule is what guarantees
`sum(sizes) == total`, which the fixture shows Tableau relies on.

### Step 5 - `compiler/workbook.py`: `_build_dashboard(dash)`

Emit, strictly in this order (§3):

1. `layout-options/title/formatted-text/run` - only if `dash.title`; reuse the
   existing `<run>` pattern from `_build_worksheet`.
2. `<style/>` - empty.
3. `<size>` - `sizing-mode="fixed"` plus the four pixel bounds, or
   `sizing-mode="automatic"` alone.
4. `<datasources>` + `<datasource-dependencies>` - **only** if any item is a
   filter/legend. Reuse `self._ds_names`, `_instance_name`, `_qualified`; the
   `<column>`/`<column-instance>` emitter is a near-copy of the block at
   `workbook.py:326-355` and should be factored into a shared helper rather than
   duplicated.
5. `<zones>` - root `<zone type="layout-basic" x=0 y=0 w=100000 h=100000
   id=alloc.take()>`, containing one
   `<zone type="layout-flow" param="vert"|"horz">`, containing a `type="title"`
   zone (if titled) plus one zone per item, coordinates from `_tile`.
   Append the root's `<zone-style>` **last** (§4.2).

A small `_zone_style(margin)` helper emits the four `<format>` children.

### Step 6 - `compiler/workbook.py`: wire into `build()`

After the `worksheets` loop (line 436) and **before** `windows` (line 438):

```python
if self.spec.dashboards:
    db_parent = ET.SubElement(root, "dashboards")
    for dash in self.spec.dashboards:
        db_parent.append(self._build_dashboard(dash))
```

Then, inside the existing `windows` block, append one dashboard window per
dashboard - **no `<cards>`** (§7):

```python
for dash in self.spec.dashboards:
    win = ET.SubElement(windows, "window",
                        {"class": "dashboard", "maximized": "true", "name": dash.name})
    vps = ET.SubElement(win, "viewpoints")
    for ws_name in dash.worksheet_names():
        ET.SubElement(vps, "viewpoint", {"name": ws_name})
    ET.SubElement(win, "active", {"id": "-1"})
```

Note `maximized="true"` currently goes on the *first worksheet* window
(line 443). Decide deliberately: if a dashboard exists it should be the maximized
window, and the worksheet windows should drop `maximized`.

### Step 7 - `validation/structure.py`: layer-2 checks

Extend `validate_generated` with dashboard-specific `Issue`s:

- `dashboard_mismatch` - `<dashboard>` names in the file match `spec.dashboards`;
- `unresolved_zone_worksheet` (**error**) - every zone with `@name` and no
  `@type` names a worksheet that exists in `<worksheets>`. This is the
  highest-value check, because the reference is a bare name string;
- `zone_out_of_range` (**error**) - any `x/y/w/h` outside `0..100000`;
- `zone_tiling` (**error**) - children of a `layout-flow` do not sum to the
  parent's extent on the flow axis;
- `missing_dashboard_window` (**error**) - a `<dashboard>` with no matching
  `<window class="dashboard">`;
- `dashboard_window_has_cards` (**error**) - guards against copy-paste from the
  worksheet-window builder;
- `unresolved_dashboard_column` (**error**) - a `filter`/`color` zone whose
  `@param` is not declared in the dashboard's own `<datasource-dependencies>`;
- `published_only_element` (**error**) - assert no `repository-location`,
  `simple-id`, `devicelayouts` or `type-v2` anywhere in the output.

### Step 8 - schema, tests, docs

- `schemas/`: add the `dashboards` array to the JSON Schema (it is currently
  accepted as a top-level key at `spec.py:182` but forced empty).
- `tests/unit/`: unit-test `_tile` for exact tiling at n = 1..7; a
  spec-validation test that a dashboard referencing an unknown worksheet raises
  `SpecError`; a determinism test that two compiles are byte-identical.
- `tests/fixtures/`: a `dashboard_spec.json`.
- Update `docs/architecture/CAPABILITY_BOUNDARY.md` and `docs/LIMITATIONS.md`.
- **Manual gate:** open the generated `.twbx` in Tableau Public 2026.2.0 before
  declaring support. Everything in this document is derived from builds
  2019.4.3–2023.1.0; nothing here has been round-tripped through 2026.2.0.

---

## 12. RISKS / UNKNOWNS

Stated plainly, verified separated from inferred.

### 12.1 No fixture was written by our target build - this is the top risk
**Verified:** doc `version` is `18.1` in the primary fixture, matching our pinned
`DOC_VERSION`. **Not verified:** that build **2026.2.0** accepts this structure.
The newest fixture available was written by 2023.1.0, three years older than the
runtime this project targets. The compiler was built against a 2026.2.0
worksheet fixture; the dashboard work has no such luxury. **`type-v2` is the
specific worry** - the task brief named it, which suggests someone has seen it
somewhere, yet it appears in **zero** of the four downloaded files. If 2026.2.0
requires `type-v2` on zones, everything here fails at load with a
`no declaration found` style error. *Mitigation:* the very first implementation
step should be to generate a two-worksheet dashboard and open it in the real
Tableau Public 2026.2.0. That single test resolves this risk and several others
below; without it, the plan above is a well-evidenced hypothesis, not a
guarantee.

### 12.2 Container nesting may be stricter than the plan assumes
**Verified:** the 18.1 fixture alternates `layout-basic → layout-flow →
layout-basic → layout-flow`. **Inferred:** that the extra `layout-basic`
wrappers are editing artefacts and a generator may nest `layout-flow` directly
inside the root `layout-basic`. My evidence for the simpler nesting comes from
the **8.3** fixture (`layout-flow` inside `layout-flow`), a different document
version. If 18.1 requires a `layout-basic` wrapper around each flow container,
the plan's zone tree is wrong. *Mitigation:* if the first load fails, mirror the
18.1 alternation exactly before changing anything else - it costs one extra zone
per level and is known-good.

### 12.3 The worksheet reference is an unvalidated name string
**Verified:** `<zone name="Sheet Name">` with no `@type` is the *only* link
between a dashboard and a worksheet - no id, no `worksheet=` attribute. A typo,
a trailing space, or a later rename produces a file that is structurally valid,
loads without error, and renders an empty box. Note the 10.4 fixture's dashboard
is literally named `"Sample DAshboard "` with a trailing space, so Tableau does
not normalise these strings. *Mitigation:* the `unresolved_zone_worksheet`
layer-2 check in Step 7 is not optional - it is the only thing standing between a
rename and a silently broken dashboard.

### 12.4 Genuinely unverified specifics
- Whether `<style/>` is **required** - present in 3/3 fixtures, so we emit it,
  but I never tested removal.
- Whether `<viewpoints>` is required, or may be empty, in the dashboard window.
- Whether `<layout-cache>` is optional. I recommend omitting it on the inference
  that "cache" means recomputed, but I did not verify this, and 4 zones in the
  fixtures do carry it.
- Whether `<zone-style>` is required, or whether a zone may have none.
- Whether zone `id`s must avoid colliding with ids used elsewhere in the
  workbook (worksheet windows have no ids, so probably not - inferred).
- The serialisation of `sizing-mode="Range"`, which Tableau's UI offers but no
  fixture used. Do not emit it.
- Whether `pane-specification-id` on a `color` zone must match something real in
  the worksheet, or whether `"0"` is always safe. Both fixtures use `"0"`.

### 12.5 Rounding will silently misplace zones
**Verified:** siblings tile their parent's extent *exactly* (sum of six child
widths = 99064 = parent width). Integer division over N items will not sum to
100000 for most N. `_tile`'s "last span absorbs the remainder" rule handles this,
but any hand-written coordinate arithmetic elsewhere in the compiler will
reintroduce the bug, and the failure mode is a subtly clipped or overlapping
dashboard rather than a load error. The `zone_tiling` layer-2 check exists
specifically to catch this.

### 12.6 Two different units in the same element
**Verified:** `x/y/w/h` are 0..100000 normalised, while `fixed-size` on the same
zone and `min/maxwidth` on `<size>` are **pixels**. A compiler that treats them
uniformly will produce zones that are off by a factor of ~80. Keep the two unit
systems in separately-named variables.

### 12.7 Scope creep beyond what is evidenced
`paramctrl` needs parameter support the project does not have; `bitmap` needs an
`Image/` entry in the `.twbx` and a packaging change; `<actions>` needs a whole
action model. Each is documented above so the shape is known, but none should be
implemented from this document alone - the fixtures show one example of each,
which is not enough to generalise from.
