"""Authoring specification model and semantic validation.

Layer 1 of the validation stack (§14). JSON Schema handles structural validation;
this module handles semantics that a schema cannot express: cross-references
between worksheets and data sources, field existence, and encoding compatibility.

**Dashboards are EXPERIMENTAL / UNVERIFIED.** Every other part of this model
describes XML that has been generated, opened in Tableau Public 2026.2.0 and
rendered. The ``dashboards`` section does not: it was reverse-engineered from
published fixtures at document version 18.1 written by older Tableau builds
(docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md), and no generated dashboard has
ever been loaded by Tableau. See :class:`Dashboard`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

from ..compiler.fields import VALID_DATATYPES, Field, infer_fields, role_and_type
from ..compiler.ids import calculation_name
from ..security.paths import resolve_input_file, resolve_output_dir

SPEC_VERSION = "0.1"

# Worksheet patterns this version can actually produce. Kept in lockstep with
# docs/architecture/CAPABILITY_BOUNDARY.md — do not add a name here unless the
# compiler emits it and a live test has opened it in Tableau.
SUPPORTED_TEMPLATES = (
    "bar",
    "line",
    "text_table",
    "heatmap",
    "scatter",
    "circle",
)

# How a worksheet fills its canvas. Omitting it uses Tableau's "Standard" fit,
# which draws a small viz tucked into the top-left corner.
FIT_MODES = ("standard", "fit_width", "fit_height", "entire_view")

AGGREGATIONS = ("Sum", "Avg", "Min", "Max", "Count", "CountD", "None", "Attribute")

# ---------------------------------------------------------------- dashboards
# EXPERIMENTAL / UNVERIFIED. Dashboard support is derived from forensic analysis
# of published fixtures at document version 18.1 (see
# docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md). No fixture written by the target
# build 2026.2.0 was available, so no generated dashboard has ever been opened in
# Tableau. Everything below compiles and validates structurally; none of it is
# confirmed to load. Do not promote it in CAPABILITY_BOUNDARY.md until it has.
DASHBOARD_DIRECTIONS = ("vertical", "horizontal")

# Only the two sizing modes the fixtures actually show for a whole dashboard.
# 'vscroll' was seen only on a device layout and 'Range' was never serialised in
# any fixture, so neither is offered.
DASHBOARD_SIZING_MODES = ("fixed", "automatic")

DASHBOARD_DEFAULT_WIDTH = 1200
DASHBOARD_DEFAULT_HEIGHT = 800
DASHBOARD_MIN_PX = 100
DASHBOARD_MAX_PX = 10000
DASHBOARD_MAX_ZONES = 20

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-.,()/&'%:+#]{0,119}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class SpecError(ValueError):
    """A specification problem with an actionable message."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SpecError(msg)


def _check_name(value: str, what: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{what} must be a non-empty string")
    value = value.strip()
    _require(
        bool(_NAME_RE.match(value)),
        f"{what} contains unsupported characters or is too long: {value!r}. "
        f"Use letters, digits, spaces and . , - _ ( ) / & ' % : + #",
    )
    return value


def _check_id(value: str, what: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{what} must be a string")
    _require(
        bool(_ID_RE.match(value)),
        f"{what} must be lowercase alphanumeric/underscore starting with a letter: {value!r}",
    )
    return value


@dataclass
class EncodingRef:
    """A field reference plus optional aggregation used on a shelf or encoding."""

    field: str
    aggregation: str = "None"

    @classmethod
    def parse(cls, raw: Any, ctx: str) -> EncodingRef:
        if isinstance(raw, str):
            return cls(field=raw, aggregation="None")
        if isinstance(raw, dict):
            unknown = set(raw) - {"field", "aggregation"}
            _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
            _require("field" in raw, f"{ctx}: missing 'field'")
            agg = raw.get("aggregation", "None")
            _require(
                agg in AGGREGATIONS,
                f"{ctx}: unsupported aggregation {agg!r}; expected one of {AGGREGATIONS}",
            )
            return cls(field=raw["field"], aggregation=agg)
        raise SpecError(f"{ctx}: must be a field name or an object with 'field'")


@dataclass
class CalculatedField:
    name: str
    data_source: str
    formula: str
    datatype: str = "string"


@dataclass
class Filter:
    field: str
    data_source: str


@dataclass
class Worksheet:
    name: str
    template: str
    data_source: str
    rows: list[EncodingRef] = dc_field(default_factory=list)
    columns: list[EncodingRef] = dc_field(default_factory=list)
    color: EncodingRef | None = None
    size: EncodingRef | None = None
    label: EncodingRef | None = None
    # Tableau's Detail shelf, compiled to <lod>. A list, because Tableau accepts
    # several fields there. Each dimension on Detail adds a grouping key, which
    # is how a sheet gets one mark per entity instead of one mark per Color
    # value. See compiler/workbook.py::_build_worksheet.
    detail: list[EncodingRef] = dc_field(default_factory=list)
    tooltips: list[EncodingRef] = dc_field(default_factory=list)
    filters: list[str] = dc_field(default_factory=list)
    title: str | None = None
    subtitle: str | None = None
    fit: str | None = None


@dataclass
class DashboardZone:
    """One worksheet placed on a dashboard.

    EXPERIMENTAL / UNVERIFIED — see :class:`Dashboard`.

    The compiled zone references its worksheet by **bare name string** (there is
    no id-based link in the ``.twb`` format), so ``worksheet`` must match a
    :class:`Worksheet` name exactly. A mismatch produces a file that loads
    without complaint and renders an empty box, which is why the reference is
    checked in layer 1 here *and* again in layer 2
    (``validation.structure.unresolved_zone_worksheet``).
    """

    worksheet: str
    show_title: bool = True

    @classmethod
    def parse(cls, raw: Any, ctx: str) -> DashboardZone:
        if isinstance(raw, str):
            return cls(worksheet=raw)
        if isinstance(raw, dict):
            unknown = set(raw) - {"worksheet", "show_title"}
            _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
            _require("worksheet" in raw, f"{ctx}: missing 'worksheet'")
            name = raw["worksheet"]
            _require(isinstance(name, str) and bool(name), f"{ctx}.worksheet must be a string")
            show_title = raw.get("show_title", True)
            _require(isinstance(show_title, bool), f"{ctx}.show_title must be a boolean")
            return cls(worksheet=name, show_title=show_title)
        raise SpecError(f"{ctx}: must be a worksheet name or an object with 'worksheet'")


@dataclass
class Dashboard:
    """A dashboard: a title plus worksheets stacked in one layout container.

    **EXPERIMENTAL / UNVERIFIED.** The XML this compiles to was reverse-engineered
    from published workbooks at document version 18.1 written by Tableau builds
    2019.4.3-2023.1.0 (docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md). The build this
    project targets is 2026.2.0, and **no generated dashboard has been opened in
    Tableau**. Treat a compiled dashboard as a well-evidenced hypothesis, not a
    supported feature: it may fail to load. The single largest unknown is whether
    2026.2.0 requires a ``type-v2`` attribute on zones — the attribute appears in
    zero fixtures across document versions 8.3/10.4/18.1, so the compiler emits
    plain ``type``.

    Scope is deliberately the smallest thing the fixtures fully evidence: a fixed
    or automatic canvas, an optional title, and worksheets tiled in one
    horizontal or vertical container. Filter cards, colour legends, highlighters,
    parameter controls, images, floating zones, device layouts and dashboard
    actions are all understood (they are catalogued in the analysis) but are not
    generated.
    """

    name: str
    worksheets: list[DashboardZone]
    direction: str = "vertical"
    title: str | None = None
    width: int = DASHBOARD_DEFAULT_WIDTH
    height: int = DASHBOARD_DEFAULT_HEIGHT
    sizing_mode: str = "fixed"

    def worksheet_names(self) -> list[str]:
        return [z.worksheet for z in self.worksheets]


@dataclass
class DataSourceSpec:
    id: str
    path: Path
    fields: list[Field]
    # Populated during the build: Tableau Public requires extract-backed sources.
    hyper_path: Path | None = None
    row_count: int = 0

    def field_map(self) -> dict[str, Field]:
        return {f.name: f for f in self.fields}

    @property
    def hyper_name(self) -> str:
        return f"{self.id}.hyper"


@dataclass
class WorkbookSpec:
    name: str
    description: str
    data_sources: list[DataSourceSpec]
    worksheets: list[Worksheet]
    output_dir: Path
    dashboards: list[Dashboard] = dc_field(default_factory=list)
    package_twbx: bool = True
    spec_version: str = SPEC_VERSION

    def data_source(self, ds_id: str) -> DataSourceSpec:
        for ds in self.data_sources:
            if ds.id == ds_id:
                return ds
        raise SpecError(f"unknown data_source id: {ds_id!r}")


def _mark_requirements(template: str) -> tuple[bool, bool]:
    """(requires_rows, requires_columns) for a template."""
    return {
        "bar": (True, True),
        "line": (True, True),
        "text_table": (True, False),
        "heatmap": (True, True),
        "scatter": (True, True),
        "circle": (True, True),
    }[template]


def parse_spec(raw: dict[str, Any]) -> WorkbookSpec:
    """Parse and semantically validate an authoring specification.

    Raises SpecError with an actionable message on the first problem found.
    """
    _require(isinstance(raw, dict), "specification must be a JSON object")

    allowed_top = {
        "spec_version",
        "workbook",
        "data_sources",
        "calculated_fields",
        "worksheets",
        "dashboards",
        "output",
    }
    unknown = set(raw) - allowed_top
    _require(not unknown, f"unknown top-level keys: {sorted(unknown)}")

    version = raw.get("spec_version", SPEC_VERSION)
    _require(
        version == SPEC_VERSION,
        f"unsupported spec_version {version!r}; this server implements {SPEC_VERSION!r}",
    )

    wb = raw.get("workbook") or {}
    _require(isinstance(wb, dict), "'workbook' must be an object")
    unknown = set(wb) - {"name", "description"}
    _require(not unknown, f"workbook: unknown keys {sorted(unknown)}")
    wb_name = _check_name(wb.get("name", ""), "workbook.name")
    wb_desc = str(wb.get("description", "")).strip()

    # ---- data sources -----------------------------------------------------
    raw_ds = raw.get("data_sources") or []
    _require(isinstance(raw_ds, list) and raw_ds, "'data_sources' must be a non-empty array")
    data_sources: list[DataSourceSpec] = []
    seen_ds: set[str] = set()
    for i, d in enumerate(raw_ds):
        ctx = f"data_sources[{i}]"
        _require(isinstance(d, dict), f"{ctx} must be an object")
        unknown = set(d) - {"id", "type", "path"}
        _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
        ds_id = _check_id(d.get("id", ""), f"{ctx}.id")
        _require(ds_id not in seen_ds, f"{ctx}: duplicate data source id {ds_id!r}")
        seen_ds.add(ds_id)
        ds_type = d.get("type", "csv")
        _require(ds_type == "csv", f"{ctx}: only type 'csv' is supported in v{SPEC_VERSION}")
        path = resolve_input_file(d.get("path", ""), must_suffix=".csv")
        data_sources.append(DataSourceSpec(id=ds_id, path=path, fields=infer_fields(path)))

    ds_by_id = {d.id: d for d in data_sources}

    # ---- calculated fields ------------------------------------------------
    for i, c in enumerate(raw.get("calculated_fields") or []):
        ctx = f"calculated_fields[{i}]"
        _require(isinstance(c, dict), f"{ctx} must be an object")
        unknown = set(c) - {"name", "data_source", "formula", "datatype"}
        _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
        name = _check_name(c.get("name", ""), f"{ctx}.name")
        ds_id = c.get("data_source", "")
        _require(ds_id in ds_by_id, f"{ctx}: unknown data_source {ds_id!r}")
        formula = c.get("formula", "")
        _require(
            isinstance(formula, str) and formula.strip(),
            f"{ctx}.formula must be a non-empty string",
        )
        datatype = c.get("datatype", "string")
        _require(
            datatype in VALID_DATATYPES,
            f"{ctx}.datatype must be one of {VALID_DATATYPES}, got {datatype!r}",
        )
        ds = ds_by_id[ds_id]
        _require(
            name not in ds.field_map(),
            f"{ctx}: calculated field {name!r} collides with an existing column in {ds_id!r}",
        )
        role, ftype = role_and_type(datatype)
        ds.fields.append(
            Field(
                name=name,
                datatype=datatype,
                role=role,
                type=ftype,
                ordinal=len(ds.fields),
                is_calculated=True,
                formula=formula,
                calc_name=calculation_name(wb_name, ds_id, name),
            )
        )

    # ---- worksheets -------------------------------------------------------
    raw_ws = raw.get("worksheets") or []
    _require(isinstance(raw_ws, list) and raw_ws, "'worksheets' must be a non-empty array")
    worksheets: list[Worksheet] = []
    seen_ws: set[str] = set()

    for i, w in enumerate(raw_ws):
        ctx = f"worksheets[{i}]"
        _require(isinstance(w, dict), f"{ctx} must be an object")
        unknown = set(w) - {
            "name",
            "template",
            "data_source",
            "rows",
            "columns",
            "color",
            "size",
            "label",
            "detail",
            "tooltips",
            "filters",
            "title",
            "subtitle",
        }
        _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")

        name = _check_name(w.get("name", ""), f"{ctx}.name")
        _require(name not in seen_ws, f"{ctx}: duplicate worksheet name {name!r}")
        seen_ws.add(name)

        template = w.get("template", "")
        _require(
            template in SUPPORTED_TEMPLATES,
            f"{ctx}: unsupported template {template!r}. Supported: {list(SUPPORTED_TEMPLATES)}",
        )
        ds_id = w.get("data_source", "")
        _require(ds_id in ds_by_id, f"{ctx}: unknown data_source {ds_id!r}")
        ds = ds_by_id[ds_id]
        fmap = ds.field_map()

        def _refs(key: str, _w: dict = w, ws_ctx: str = ctx) -> list[EncodingRef]:
            vals = _w.get(key) or []
            _require(isinstance(vals, list), f"{ws_ctx}.{key} must be an array")
            return [EncodingRef.parse(v, f"{ws_ctx}.{key}[{j}]") for j, v in enumerate(vals)]

        def _ref(key: str, _w: dict = w, ws_ctx: str = ctx) -> EncodingRef | None:
            if key not in _w or _w[key] is None:
                return None
            return EncodingRef.parse(_w[key], f"{ws_ctx}.{key}")

        rows = _refs("rows")
        columns = _refs("columns")
        color = _ref("color")
        size = _ref("size")
        label = _ref("label")
        detail = _refs("detail")
        tooltips = _refs("tooltips")

        filters = w.get("filters") or []
        _require(isinstance(filters, list), f"{ctx}.filters must be an array")
        for j, f in enumerate(filters):
            _require(isinstance(f, str), f"{ctx}.filters[{j}] must be a field name string")

        # every referenced field must exist in the worksheet's data source
        for label_, refs in (
            ("rows", rows),
            ("columns", columns),
            ("detail", detail),
            ("tooltips", tooltips),
            ("color", [color] if color else []),
            ("size", [size] if size else []),
            ("label", [label] if label else []),
        ):
            for r in refs:
                _require(
                    r.field in fmap,
                    f"{ctx}.{label_}: field {r.field!r} does not exist in data source "
                    f"{ds_id!r}. Available: {sorted(fmap)[:12]}",
                )
        for f in filters:
            _require(
                f in fmap,
                f"{ctx}.filters: field {f!r} does not exist in data source {ds_id!r}",
            )

        # Detail is a set of grouping keys, so listing a field twice is always a
        # mistake: the second copy cannot subdivide the marks any further, and
        # the compiler would collapse both into one <lod> anyway.
        seen_detail: set[str] = set()
        for r in detail:
            _require(
                r.field not in seen_detail,
                f"{ctx}.detail: field {r.field!r} appears more than once; a field can be "
                f"placed on Detail at most once",
            )
            seen_detail.add(r.field)

        fit = w.get("fit")
        _require(
            fit is None or fit in FIT_MODES,
            f"{ctx}.fit must be one of {sorted(FIT_MODES)}, got {fit!r}",
        )

        need_rows, need_cols = _mark_requirements(template)
        if need_rows:
            _require(rows, f"{ctx}: template {template!r} requires at least one 'rows' field")
        if need_cols:
            _require(columns, f"{ctx}: template {template!r} requires at least one 'columns' field")

        # encoding compatibility: quantitative encodings need a measure or an aggregation
        for enc_name, ref in (("color", color), ("size", size)):
            if ref and enc_name == "size":
                fld = fmap[ref.field]
                _require(
                    fld.is_measure or ref.aggregation not in ("None",),
                    f"{ctx}.size: size encoding needs a measure or an aggregation; "
                    f"{ref.field!r} is a dimension",
                )

        if template == "scatter":
            for shelf_name, shelf in (("rows", rows), ("columns", columns)):
                for r in shelf:
                    fld = fmap[r.field]
                    _require(
                        fld.is_measure or r.aggregation != "None",
                        f"{ctx}.{shelf_name}: 'scatter' needs aggregated measures; "
                        f"{r.field!r} is a dimension with no aggregation",
                    )

        worksheets.append(
            Worksheet(
                name=name,
                template=template,
                data_source=ds_id,
                rows=rows,
                columns=columns,
                color=color,
                size=size,
                label=label,
                detail=detail,
                tooltips=tooltips,
                filters=list(filters),
                title=w.get("title"),
                subtitle=w.get("subtitle"),
            )
        )

    # ---- dashboards -------------------------------------------------------
    # EXPERIMENTAL / UNVERIFIED — see the Dashboard docstring. Parsed and
    # compiled, but never confirmed to open in Tableau Public 2026.2.0.
    raw_db = raw.get("dashboards") or []
    _require(isinstance(raw_db, list), "'dashboards' must be an array")
    dashboards: list[Dashboard] = []
    seen_db: set[str] = set()

    for i, d in enumerate(raw_db):
        ctx = f"dashboards[{i}]"
        _require(isinstance(d, dict), f"{ctx} must be an object")
        unknown = set(d) - {
            "name",
            "title",
            "direction",
            "sizing_mode",
            "width",
            "height",
            "worksheets",
        }
        _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")

        name = _check_name(d.get("name", ""), f"{ctx}.name")
        _require(name not in seen_db, f"{ctx}: duplicate dashboard name {name!r}")
        _require(
            name not in seen_ws,
            f"{ctx}: dashboard name {name!r} collides with a worksheet name; both are "
            f"registered in <windows> by name and must be distinct",
        )
        seen_db.add(name)

        direction = d.get("direction", "vertical")
        _require(
            direction in DASHBOARD_DIRECTIONS,
            f"{ctx}: unsupported direction {direction!r}; expected one of "
            f"{list(DASHBOARD_DIRECTIONS)}",
        )

        sizing_mode = d.get("sizing_mode", "fixed")
        _require(
            sizing_mode in DASHBOARD_SIZING_MODES,
            f"{ctx}: unsupported sizing_mode {sizing_mode!r}; expected one of "
            f"{list(DASHBOARD_SIZING_MODES)}",
        )

        title = d.get("title")
        if title is not None:
            _require(
                isinstance(title, str) and bool(title.strip()),
                f"{ctx}.title must be a non-empty string",
            )
            _require(len(title) <= 300, f"{ctx}.title must be 300 characters or fewer")

        # 'fixed' declares a pixel canvas; 'automatic' fits the window and has no
        # bounds at all, so accepting a size there would silently discard it.
        if sizing_mode == "automatic":
            for key in ("width", "height"):
                _require(
                    key not in d,
                    f"{ctx}.{key} cannot be set when sizing_mode is 'automatic'; "
                    f"an automatic dashboard has no declared canvas size",
                )
        width = d.get("width", DASHBOARD_DEFAULT_WIDTH)
        height = d.get("height", DASHBOARD_DEFAULT_HEIGHT)
        for key, value in (("width", width), ("height", height)):
            _require(
                isinstance(value, int) and not isinstance(value, bool),
                f"{ctx}.{key} must be an integer number of pixels",
            )
            _require(
                DASHBOARD_MIN_PX <= value <= DASHBOARD_MAX_PX,
                f"{ctx}.{key} must be between {DASHBOARD_MIN_PX} and {DASHBOARD_MAX_PX} "
                f"pixels, got {value}",
            )

        raw_zones = d.get("worksheets") or []
        _require(
            isinstance(raw_zones, list) and bool(raw_zones),
            f"{ctx}.worksheets must be a non-empty array of worksheet names",
        )
        _require(
            len(raw_zones) <= DASHBOARD_MAX_ZONES,
            f"{ctx}.worksheets: at most {DASHBOARD_MAX_ZONES} worksheets per dashboard, "
            f"got {len(raw_zones)}",
        )
        zones: list[DashboardZone] = []
        placed: set[str] = set()
        for j, z in enumerate(raw_zones):
            zone_ctx = f"{ctx}.worksheets[{j}]"
            zone = DashboardZone.parse(z, zone_ctx)
            # The zone->worksheet link is a bare name string with no id behind it,
            # so an unresolvable name yields an empty box, not an error (§4.4).
            _require(
                zone.worksheet in seen_ws,
                f"{zone_ctx}: worksheet {zone.worksheet!r} does not exist. "
                f"Available: {sorted(seen_ws)}",
            )
            _require(
                zone.worksheet not in placed,
                f"{zone_ctx}: worksheet {zone.worksheet!r} is already placed on dashboard "
                f"{name!r}; a worksheet can appear at most once per dashboard",
            )
            placed.add(zone.worksheet)
            zones.append(zone)

        dashboards.append(
            Dashboard(
                name=name,
                worksheets=zones,
                direction=direction,
                title=title,
                width=width,
                height=height,
                sizing_mode=sizing_mode,
            )
        )

    out = raw.get("output") or {}
    _require(isinstance(out, dict), "'output' must be an object")
    unknown = set(out) - {"directory", "package_twbx"}
    _require(not unknown, f"output: unknown keys {sorted(unknown)}")
    _require("directory" in out, "output.directory is required")
    out_dir = resolve_output_dir(out["directory"])
    package = out.get("package_twbx", True)
    _require(isinstance(package, bool), "output.package_twbx must be a boolean")

    return WorkbookSpec(
        name=wb_name,
        description=wb_desc,
        data_sources=data_sources,
        worksheets=worksheets,
        output_dir=out_dir,
        dashboards=dashboards,
        package_twbx=package,
    )
