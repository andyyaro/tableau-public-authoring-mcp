"""Layer 2 validation — generated-file structural checks (§14)."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: S405 - entity declarations blocked by _parse_twb
import xml.parsers.expat  # noqa: S405 - used to REJECT entity declarations, not to parse
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..models.spec import WorkbookSpec
from ..security.paths import PathSecurityError, safe_archive_name

ZONE_GRID = 100000

#: Largest ``.twb`` this module will parse. ElementTree builds the whole tree in
#: memory, so without a ceiling the file's author picks the peak RSS.
MAX_TWB_BYTES = 64 * 1024 * 1024

# Elements Tableau writes only when publishing, plus one attribute that appears
# in no fixture at any document version. None may ever reach a generated file.
_PUBLISHED_ONLY_TAGS = ("repository-location", "simple-id", "devicelayouts", "devicelayout")
_FORBIDDEN_ZONE_ATTRS = ("type-v2",)


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def _zone_box(zone: ET.Element) -> dict[str, int] | None:
    """Parse a zone's ``x/y/w/h`` grid geometry, or None if it is not intact."""
    box: dict[str, int] = {}
    for attr in ("x", "y", "w", "h"):
        raw = zone.get(attr)
        if raw is None:
            return None
        try:
            box[attr] = int(raw)
        except ValueError:
            return None
    return box


def _check_zone(
    zone: ET.Element,
    dash_name: str,
    ws_names: set[str],
    seen_ids: set[str],
    issues: list[Issue],
) -> None:
    """Recursively check one zone subtree of a dashboard."""
    where = f"dashboard {dash_name!r}"

    for attr in _FORBIDDEN_ZONE_ATTRS:
        if zone.get(attr) is not None:
            issues.append(
                Issue(
                    "error",
                    "published_only_element",
                    f"{where}: zone carries @{attr}, which appears in no fixture at any "
                    f"document version and must not be emitted",
                )
            )

    zone_id = zone.get("id")
    if not zone_id or not zone_id.isdigit():
        issues.append(
            Issue(
                "error",
                "bad_zone_id",
                f"{where}: zone id {zone_id!r} is not a small positive integer; Tableau "
                f"uses integer zone ids, not hashed identifiers",
            )
        )
    elif zone_id in seen_ids:
        issues.append(Issue("error", "dup_zone_id", f"{where}: duplicate zone id {zone_id!r}"))
    else:
        seen_ids.add(zone_id)

    box = _zone_box(zone)
    if box is None:
        issues.append(
            Issue(
                "error",
                "zone_geometry",
                f"{where}: zone {zone_id!r} is missing or has non-integer x/y/w/h",
            )
        )
    else:
        for attr, value in box.items():
            if not 0 <= value <= ZONE_GRID:
                issues.append(
                    Issue(
                        "error",
                        "zone_out_of_range",
                        f"{where}: zone {zone_id!r} has @{attr}={value}, outside the "
                        f"0..{ZONE_GRID} normalised grid",
                    )
                )
        for start, size, axis in ((box["x"], box["w"], "x+w"), (box["y"], box["h"], "y+h")):
            if start + size > ZONE_GRID:
                issues.append(
                    Issue(
                        "error",
                        "zone_out_of_range",
                        f"{where}: zone {zone_id!r} extends past the grid ({axis}="
                        f"{start + size} > {ZONE_GRID})",
                    )
                )

    # A zone with @name and NO @type renders a worksheet, and the link is a bare
    # name string: an unresolvable name loads fine and renders an empty box, so
    # this check is the only thing that catches a typo or a rename.
    if zone.get("type") is None and zone.get("name") is not None:
        name = zone.get("name")
        if name not in ws_names:
            issues.append(
                Issue(
                    "error",
                    "unresolved_zone_worksheet",
                    f"{where}: zone {zone_id!r} references worksheet {name!r}, which does "
                    f"not exist in <worksheets>. Tableau would render an empty box "
                    f"without any error. Available: {sorted(ws_names)}",
                )
            )

    children = [c for c in zone if c.tag == "zone"]
    tags = [c.tag for c in zone]
    if "zone-style" in tags and tags[-1] != "zone-style":
        issues.append(
            Issue(
                "error",
                "zone_child_order",
                f"{where}: zone {zone_id!r} has <zone-style> before its nested zones; "
                f"zone-style is last in every fixture zone that has one",
            )
        )

    # Siblings inside a layout container must tile the parent's extent exactly.
    if zone.get("type") == "layout-flow" and children and box is not None:
        vertical = zone.get("param") == "vert"
        start_key, size_key = ("y", "h") if vertical else ("x", "w")
        cursor = box[start_key]
        ok = True
        for child in children:
            cbox = _zone_box(child)
            if cbox is None:
                ok = False
                break
            if cbox[start_key] != cursor:
                ok = False
                break
            cursor += cbox[size_key]
        if not ok or cursor != box[start_key] + box[size_key]:
            issues.append(
                Issue(
                    "error",
                    "zone_tiling",
                    f"{where}: children of layout-flow zone {zone_id!r} do not tile its "
                    f"{size_key} extent exactly; the dashboard would be clipped or "
                    f"overlapping rather than fail to load",
                )
            )

    for child in children:
        _check_zone(child, dash_name, ws_names, seen_ids, issues)


def _check_dashboards(root: ET.Element, spec: WorkbookSpec, ws_names: set[str]) -> list[Issue]:
    """Layer-2 checks for the EXPERIMENTAL ``<dashboards>`` section.

    These are structural only. They cannot tell you whether Tableau Public
    2026.2.0 will actually open the file — nothing in this project can, until a
    generated dashboard is loaded by hand.
    """
    issues: list[Issue] = []
    db_nodes = root.find("dashboards")

    if not spec.dashboards:
        if db_nodes is not None:
            issues.append(
                Issue(
                    "error",
                    "unexpected_dashboards",
                    "<dashboards> is present but the spec requested no dashboards",
                )
            )
        return issues

    if db_nodes is None or not len(db_nodes):
        issues.append(
            Issue(
                "error",
                "missing_dashboards",
                f"spec requested {len(spec.dashboards)} dashboard(s) but the file has no "
                f"<dashboard> elements",
            )
        )
        return issues

    # <dashboards> must sit between <worksheets> and <windows>.
    order = [c.tag for c in root]
    if "worksheets" in order and "windows" in order:
        if not order.index("worksheets") < order.index("dashboards") < order.index("windows"):
            issues.append(
                Issue(
                    "error",
                    "dashboards_position",
                    f"<dashboards> must sit between <worksheets> and <windows>; got {order}",
                )
            )

    seen: set[str] = set()
    for dash in db_nodes:
        name = dash.get("name") or ""
        if name in seen:
            issues.append(Issue("error", "dup_dashboard", f"duplicate dashboard name: {name!r}"))
        seen.add(name)

        # Tableau's loader enforces a DTD content model: layout-options?, style,
        # size, datasources?, datasource-dependencies*, zones.
        allowed = [
            "layout-options",
            "style",
            "size",
            "datasources",
            "datasource-dependencies",
            "zones",
        ]
        tags = [c.tag for c in dash]
        unknown = [t for t in tags if t not in allowed]
        if unknown:
            issues.append(
                Issue(
                    "error",
                    "dashboard_child_order",
                    f"dashboard {name!r} contains unsupported children {unknown}",
                )
            )
        else:
            ranks = [allowed.index(t) for t in tags]
            if ranks != sorted(ranks):
                issues.append(
                    Issue(
                        "error",
                        "dashboard_child_order",
                        f"dashboard {name!r} children {tags} are misordered; Tableau's "
                        f"content model requires {allowed}",
                    )
                )
        for required in ("style", "size", "zones"):
            if dash.find(required) is None:
                issues.append(
                    Issue(
                        "error",
                        "dashboard_child_order",
                        f"dashboard {name!r} is missing required <{required}>",
                    )
                )

        # A title needs both the text and a zone to display it; either alone is a
        # silent no-op.
        has_title_text = dash.find("layout-options/title") is not None
        has_title_zone = any(z.get("type") == "title" for z in dash.iter("zone"))
        if has_title_text != has_title_zone:
            half = (
                "title text but no type='title' zone"
                if has_title_text
                else "a type='title' zone but no title text"
            )
            issues.append(
                Issue(
                    "error",
                    "dashboard_title_halfway",
                    f"dashboard {name!r} has {half}; a dashboard title needs both pieces "
                    f"or it renders nothing",
                )
            )

        zones = dash.find("zones")
        if zones is None or len(zones) != 1:
            issues.append(
                Issue(
                    "error",
                    "dashboard_root_zone",
                    f"dashboard {name!r} must contain exactly one root <zone>, "
                    f"found {0 if zones is None else len(zones)}",
                )
            )
        else:
            root_zone = zones[0]
            if root_zone.get("type") != "layout-basic":
                issues.append(
                    Issue(
                        "error",
                        "dashboard_root_zone",
                        f"dashboard {name!r}: root zone type is "
                        f"{root_zone.get('type')!r}, expected 'layout-basic'",
                    )
                )
            _check_zone(root_zone, name, ws_names, set(), issues)

    expected = {d.name for d in spec.dashboards}
    if seen != expected:
        issues.append(
            Issue(
                "error",
                "dashboard_mismatch",
                f"dashboards in file {sorted(seen)} do not match spec {sorted(expected)}",
            )
        )

    # Every dashboard needs a <window class='dashboard'> and, unlike a worksheet
    # window, must not carry <cards>.
    windows = root.find("windows")
    win_by_name = {
        w.get("name"): w
        for w in (windows if windows is not None else [])
        if w.get("class") == "dashboard"
    }
    for dash_name in sorted(expected):
        win = win_by_name.get(dash_name)
        if win is None:
            issues.append(
                Issue(
                    "error",
                    "missing_dashboard_window",
                    f"dashboard {dash_name!r} has no <window class='dashboard'>; Tableau "
                    f"would not show a tab for it",
                )
            )
            continue
        if win.find("cards") is not None:
            issues.append(
                Issue(
                    "error",
                    "dashboard_window_has_cards",
                    f"dashboard window {dash_name!r} contains <cards>, which belongs only "
                    f"to worksheet windows",
                )
            )
        for vp in win.iter("viewpoint"):
            if vp.get("name") not in ws_names:
                issues.append(
                    Issue(
                        "error",
                        "unresolved_zone_worksheet",
                        f"dashboard window {dash_name!r} has a viewpoint for unknown "
                        f"worksheet {vp.get('name')!r}",
                    )
                )

    return issues


def _check_published_only(root: ET.Element) -> list[Issue]:
    """Publish-server metadata must never appear in a generated file."""
    issues: list[Issue] = []
    for tag in _PUBLISHED_ONLY_TAGS:
        if root.find(f".//{tag}") is not None:
            issues.append(
                Issue(
                    "error",
                    "published_only_element",
                    f"<{tag}> is publish-server metadata and must not be generated",
                )
            )
    return issues


class _EntityDeclarationFound(Exception):
    """Internal signal: the document declares an entity."""


class _RootElementReached(Exception):
    """Internal signal: the prolog is over, so every declaration has been seen."""


def _reject_entity_declarations(path: Path) -> None:
    """Refuse a document that declares XML entities, before ElementTree sees it.

    The comment this replaces claimed ElementTree was immune to billion-laughs.
    Half of that was right and half was badly wrong:

    * XXE — correct. An external entity is never fetched; the reference raises
      ``undefined entity``, verified against ``<!ENTITY xxe SYSTEM "file:///etc/passwd">``.
    * billion-laughs — wrong. Internal entities ARE expanded. A 343-byte ``.twb``
      with six levels of ten-fold nesting expands to 1,000,000 characters inside
      ``ET.parse``, and each further level multiplies that by ten.

    The defence needs no new dependency. Entity declarations live in the internal
    DTD subset, which is entirely before the root element, and expat reports each
    declaration *without* expanding it — nothing is expanded until a reference is
    encountered in content, which happens later. So a pre-pass that stops at the
    root element start tag has seen every declaration while having done no work
    proportional to their expansion. It reads only the prolog.

    Nothing legitimate is lost: Tableau writes no DOCTYPE, and a ``.twb`` needs
    no entities beyond the five XML predefines, which are not declarations.
    """
    size = path.stat().st_size
    if size > MAX_TWB_BYTES:
        raise PathSecurityError(
            f".twb exceeds {MAX_TWB_BYTES} bytes and will not be parsed: {size}"
        )

    parser = xml.parsers.expat.ParserCreate()

    def _on_entity_decl(name, *_args):
        raise _EntityDeclarationFound(name)

    def _on_start_element(*_args):
        raise _RootElementReached

    parser.EntityDeclHandler = _on_entity_decl
    parser.StartElementHandler = _on_start_element
    # Belt and braces: never dereference an external DTD subset or entity.
    parser.ExternalEntityRefHandler = lambda *_args: False

    try:
        with path.open("rb") as fh:
            parser.ParseFile(fh)
    except _RootElementReached:
        return
    except _EntityDeclarationFound as exc:
        raise PathSecurityError(
            f".twb declares XML entity {str(exc)!r}; entity declarations are refused because "
            f"nested internal entities expand exponentially during parsing"
        ) from exc
    except xml.parsers.expat.ExpatError:
        # Malformed prolog. Let ElementTree produce the real diagnostic below.
        return


def _parse_twb(path: Path) -> ET.Element:
    """Parse a ``.twb`` after refusing entity declarations. Raises PathSecurityError."""
    _reject_entity_declarations(path)
    return ET.parse(path).getroot()  # noqa: S314 - prolog vetted above


def _has_populated_shelf(ws: ET.Element) -> bool:
    """True if the worksheet puts at least one field on a shelf or an encoding.

    The presence test this replaces could never be false. The compiler emits
    ``<rows>``, ``<cols>`` and ``<encodings>`` unconditionally, so
    ``find(".//rows") is not None`` and ``any(ws.iter("encodings"))`` were both
    always true and ``empty_worksheet`` was dead code — a rows-only text table
    ships ``<encodings />`` and ``<cols />`` and would have passed with every
    shelf empty. What matters is whether those elements have anything *in* them:
    ``<rows>``/``<cols>`` carry their pills as text, ``<encodings>`` as children.
    """
    for tag in ("rows", "cols"):
        for el in ws.iter(tag):
            if (el.text or "").strip():
                return True
    return any(len(enc) for enc in ws.iter("encodings"))


def validate_generated(twb_path: Path, twbx_path: Path | None, spec: WorkbookSpec) -> list[Issue]:
    issues: list[Issue] = []

    # --- .twb is well-formed XML with the required skeleton ----------------
    try:
        root = _parse_twb(twb_path)
    except PathSecurityError as exc:
        return [Issue("error", "xml_unsafe", str(exc))]
    except ET.ParseError as exc:
        return [Issue("error", "xml_malformed", f".twb is not well-formed XML: {exc}")]

    if root.tag != "workbook":
        issues.append(
            Issue("error", "bad_root", f"root element is <{root.tag}>, expected <workbook>")
        )
    for attr in ("version", "source-build", "source-platform"):
        if not root.get(attr):
            issues.append(Issue("error", "missing_attr", f"workbook is missing @{attr}"))

    ds_nodes = root.find("datasources")
    ws_nodes = root.find("worksheets")
    if ds_nodes is None or not len(ds_nodes):
        issues.append(Issue("error", "no_datasources", "workbook contains no <datasource>"))
    if ws_nodes is None or not len(ws_nodes):
        issues.append(Issue("error", "no_worksheets", "workbook contains no <worksheet>"))

    if ds_nodes is not None and ws_nodes is not None:
        ds_names = {d.get("name") for d in ds_nodes}

        # worksheet names unique and matching the spec
        seen: set[str] = set()
        for w in ws_nodes:
            nm = w.get("name") or ""
            if nm in seen:
                issues.append(Issue("error", "dup_worksheet", f"duplicate worksheet name: {nm!r}"))
            seen.add(nm)

        expected = {w.name for w in spec.worksheets}
        if seen != expected:
            issues.append(
                Issue(
                    "error",
                    "worksheet_mismatch",
                    f"worksheets in file {sorted(seen)} do not match spec {sorted(expected)}",
                )
            )

        # every datasource reference resolves
        for w in ws_nodes:
            for dep in w.iter("datasource-dependencies"):
                ref = dep.get("datasource")
                if ref not in ds_names:
                    issues.append(
                        Issue(
                            "error",
                            "unresolved_datasource",
                            f"worksheet {w.get('name')!r} references unknown data source {ref!r}",
                        )
                    )

            # a publishable sheet must carry at least one encoding or shelf entry
            if not _has_populated_shelf(w):
                issues.append(
                    Issue(
                        "error",
                        "empty_worksheet",
                        f"worksheet {w.get('name')!r} has no fields on any shelf; Tableau will "
                        f"not offer 'Save to Tableau Public' for a field-less viz",
                    )
                )

            # every column-instance must point at a declared column
            for dep in w.iter("datasource-dependencies"):
                declared = {c.get("name") for c in dep.findall("column")}
                for ci in dep.findall("column-instance"):
                    if ci.get("column") not in declared:
                        issues.append(
                            Issue(
                                "error",
                                "unresolved_column",
                                f"worksheet {w.get('name')!r}: column-instance references "
                                f"undeclared column {ci.get('column')!r}",
                            )
                        )

    # --- dashboards (EXPERIMENTAL) ----------------------------------------
    file_ws_names = {w.get("name") or "" for w in (ws_nodes if ws_nodes is not None else [])}
    issues.extend(_check_dashboards(root, spec, file_ws_names))
    issues.extend(_check_published_only(root))

    # --- .twbx archive contents -------------------------------------------
    if twbx_path is not None:
        if not zipfile.is_zipfile(twbx_path):
            issues.append(Issue("error", "not_zip", f"{twbx_path.name} is not a valid ZIP archive"))
        else:
            with zipfile.ZipFile(twbx_path) as zf:
                names = zf.namelist()
            for n in names:
                try:
                    safe_archive_name(n)
                except PathSecurityError as exc:
                    issues.append(Issue("error", "unsafe_entry", str(exc)))

            twbs = [n for n in names if n.lower().endswith(".twb")]
            if len(twbs) != 1:
                issues.append(
                    Issue(
                        "error",
                        "twb_count",
                        f"expected exactly one .twb in package, found {len(twbs)}",
                    )
                )

            expected = {ds.path.name for ds in spec.data_sources}
            expected |= {ds.hyper_name for ds in spec.data_sources}
            found = {Path(n).name for n in names}
            missing = expected - found
            if missing:
                issues.append(
                    Issue(
                        "error", "missing_data", f"package is missing data files: {sorted(missing)}"
                    )
                )
            # Tableau Public requires every data source to be extract-backed.
            for ds in spec.data_sources:
                if ds.hyper_name not in found:
                    issues.append(
                        Issue(
                            "error",
                            "missing_extract",
                            f"data source {ds.id!r} has no .hyper extract in the package; "
                            f"Tableau Public rejects non-extract sources (Error 3C242D89)",
                        )
                    )

            unexpected = [n for n in names if not n.lower().endswith((".twb", ".csv", ".hyper"))]
            if unexpected:
                issues.append(
                    Issue(
                        "warning", "unexpected_entry", f"unexpected package entries: {unexpected}"
                    )
                )

    return issues
