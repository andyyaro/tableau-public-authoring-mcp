"""Authoring specification model and semantic validation.

Layer 1 of the validation stack (§14). JSON Schema handles structural validation;
this module handles semantics that a schema cannot express: cross-references
between worksheets and data sources, field existence, and encoding compatibility.

Every part of this model describes XML that has been generated, opened in Tableau
Public 2026.2.0 and rendered — including ``dashboards``, which was originally
reverse-engineered from older published fixtures and carried an
EXPERIMENTAL/UNVERIFIED warning here long after it had been confirmed to load.
See :class:`Dashboard`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

from ..compiler.fields import VALID_DATATYPES, Field, infer_fields, role_and_type
from ..compiler.ids import calculation_name
from ..security.paths import (
    PathSecurityError,
    default_base_dir,
    resolve_base_dir,
    resolve_input_file,
    resolve_output_dir,
)

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
    "map",
)

# How a worksheet fills its canvas. Omitting it uses Tableau's "Standard" fit,
# which draws a small viz tucked into the top-left corner.
FIT_MODES = ("standard", "fit_width", "fit_height", "entire_view")

AGGREGATIONS = ("Sum", "Avg", "Min", "Max", "Count", "CountD", "None", "Attribute")

# ---------------------------------------------------------- accepted key sets
# These tuples are the ONE definition of "what keys exist at each level of the
# spec". ``parse_spec`` rejects anything outside them, and ``spec_json_schema``
# turns them into the published contract's ``properties``/``additionalProperties:
# false``. They were inline set literals inside parse_spec until the published
# schema was found to be missing ``fit`` -- a key parse_spec had accepted, the
# compiler emitted and CAPABILITY_BOUNDARY.md listed as verified for weeks, while
# the schema said it was an unknown property. Two hand-maintained lists of the
# same thing is exactly how that happens, so now there is one.
#
# Order is significant: it is the property order of the generated schema, so a
# tuple keeps the published file's diffs stable where a set would not.
TOP_LEVEL_KEYS = (
    "spec_version",
    "base_dir",
    "workbook",
    "data_sources",
    "calculated_fields",
    "worksheets",
    "dashboards",
    "output",
)
WORKBOOK_KEYS = ("name", "description")
DATA_SOURCE_KEYS = ("id", "type", "path")
CALCULATED_FIELD_KEYS = ("name", "data_source", "formula", "datatype")
WORKSHEET_KEYS = (
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
    "fit",
    "latitude",
    "longitude",
)
ENCODING_REF_KEYS = ("field", "aggregation")
OUTPUT_KEYS = ("directory", "package_twbx")

# ---------------------------------------------------------------- dashboards
# Dashboard support is derived from forensic analysis of published fixtures at
# document version 18.1 (docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md); no fixture
# written by the target build 2026.2.0 was available. It is now VERIFIED against
# Tableau Public 2026.2.0 by tests/live/test_dashboard.py. Dashboard *extras*
# (filter cards, legends, floating zones, device layouts, actions) remain
# ungenerated - see capabilities.py.
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
DASHBOARD_TITLE_MAX = 300

DASHBOARD_KEYS = (
    "name",
    "title",
    "direction",
    "sizing_mode",
    "width",
    "height",
    "worksheets",
)
DASHBOARD_ZONE_KEYS = ("worksheet", "show_title")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-.,()/&'%:+#]{0,119}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# The same name rule expressed for the published schema. ``_check_name`` trims
# before matching, so a JSON Schema consumer applying _NAME_RE verbatim to the
# raw document would reject "  Site Summary  " -- which this server accepts and
# normalises. The \s* wrapper is what makes the contract agree with the code
# rather than merely resemble it; the trailing \s* also absorbs padding past the
# 120-character cap, exactly as .strip() does.
NAME_PATTERN_JSON = r"^\s*" + _NAME_RE.pattern[1:-1] + r"\s*$"

# Input and output paths go through security.paths, which calls expanduser()
# before requiring an absolute path -- so "~/data.csv" is legal and a bare "^/"
# pattern in the published schema would reject a spec this server accepts.
PATH_PATTERN_JSON = r"^[/~]"


class SpecError(ValueError):
    """A specification problem with an actionable message."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SpecError(msg)


def _check_name(value: str, what: str) -> str:
    # Both halves of the message name the offending value. "workbook.name must be
    # a non-empty string" on its own leaves the caller guessing whether the key
    # was absent, null, a number or an empty string - four different fixes.
    _require(
        isinstance(value, str) and bool(value.strip()),
        f"{what} must be a non-empty string, got {value!r}",
    )
    value = value.strip()
    _require(
        bool(_NAME_RE.match(value)),
        f"{what} contains unsupported characters or is too long: {value!r}. "
        f"Use letters, digits, spaces and . , - _ ( ) / & ' % : + #",
    )
    return value


def _check_id(value: str, what: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{what} must be a string, got {value!r}")
    _require(
        bool(_ID_RE.match(value)),
        f"{what} must be lowercase alphanumeric/underscore starting with a letter: {value!r}",
    )
    return value


def _optional_list(raw: dict[str, Any], key: str, what: str) -> list[Any]:
    """Read an optional array, treating an explicit null as "absent".

    ``raw.get(key) or []`` was used everywhere for this and swallowed more than
    null: ``{"dashboards": {}}`` and ``{"rows": 0}`` are falsy, so they became an
    empty list and the caller's dashboards were dropped in silence. A spec that
    asks for something and gets nothing, with no error, is the worst outcome this
    project has - the caller has no way to notice. Null still means absent,
    because that is how most JSON producers spell an omitted optional field.
    """
    value = raw.get(key)
    if value is None:
        return []
    _require(isinstance(value, list), f"{what} must be an array, got {type(value).__name__}")
    return value


def _check_text(value: Any, what: str) -> str | None:
    """Accept an optional free-text field, rejecting anything that is not a string.

    Non-strings used to pass layer 1 untouched and blow up much later inside the
    XML serializer: ``{"title": 42}`` reached ElementTree as an attribute value
    and raised ``TypeError: cannot serialize 42 (type int)`` from the compiler,
    with no spec path in the message. A caller cannot act on that.
    """
    if value is None:
        return None
    _require(isinstance(value, str), f"{what} must be a string, got {value!r}")
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
            unknown = set(raw) - set(ENCODING_REF_KEYS)
            _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
            _require("field" in raw, f"{ctx}: missing 'field'")
            # A non-string field name is not merely wrong, it CRASHES: the
            # existence check below is `ref.field in field_map`, and an unhashable
            # value ({"field": {"a": 1}}) raises TypeError: unhashable type
            # instead of a SpecError, so the server returns an internal error
            # rather than a fixable message.
            name = raw["field"]
            _require(
                isinstance(name, str) and bool(name),
                f"{ctx}.field must be a non-empty field-name string, got {name!r}",
            )
            agg = raw.get("aggregation", "None")
            _require(
                agg in AGGREGATIONS,
                f"{ctx}: unsupported aggregation {agg!r}; expected one of {AGGREGATIONS}",
            )
            return cls(field=name, aggregation=agg)
        raise SpecError(
            f"{ctx}: must be a field name or an object with 'field', got {raw!r}"
        )


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
    # Map axes. Structural, not encodings: the compiler puts latitude on <rows>
    # and longitude on <cols> itself, because that order is a rule of Tableau's
    # map projection rather than a choice the caller gets to make. Both are
    # inferred from the data source when the template is 'map' and they are
    # omitted. See compiler/fields.py::_GEO_ROLES.
    latitude: EncodingRef | None = None
    longitude: EncodingRef | None = None


@dataclass
class DashboardZone:
    """One worksheet placed on a dashboard.

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
            unknown = set(raw) - set(DASHBOARD_ZONE_KEYS)
            _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
            _require("worksheet" in raw, f"{ctx}: missing 'worksheet'")
            name = raw["worksheet"]
            _require(
                isinstance(name, str) and bool(name),
                f"{ctx}.worksheet must be a non-empty worksheet-name string, got {name!r}",
            )
            show_title = raw.get("show_title", True)
            _require(
                isinstance(show_title, bool),
                f"{ctx}.show_title must be a boolean, got {show_title!r}",
            )
            return cls(worksheet=name, show_title=show_title)
        raise SpecError(
            f"{ctx}: must be a worksheet name or an object with 'worksheet', got {raw!r}"
        )


@dataclass
class Dashboard:
    """A dashboard: a title plus worksheets stacked in one layout container.

    **VERIFIED** against Tableau Public 2026.2.0 by tests/live/test_dashboard.py:
    the title, both worksheet zones and the fixed 1200x800 canvas all render.

    The XML was originally reverse-engineered from published workbooks at document
    version 18.1 written by Tableau builds 2019.4.3-2023.1.0
    (docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md), and this docstring carried an
    EXPERIMENTAL / UNVERIFIED warning long after that live test passed. That is the
    same defect tests/unit/test_capability_drift.py exists to prevent: a false
    "unsupported" removes a working feature from a model's option set just as
    surely as a bug would. The open question the warning existed for -- whether
    2026.2.0 requires a ``type-v2`` attribute on zones -- is settled: it does not,
    and the compiler's plain ``type`` loads.

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
    #: Absolute anchor for every relative path in the spec, or None when all
    #: paths were absolute. A relative path is resolved against this AND required
    #: to stay inside it, so it can address nothing the author did not put here.
    base_dir: Path | None = None
    dashboards: list[Dashboard] = dc_field(default_factory=list)
    package_twbx: bool = True
    spec_version: str = SPEC_VERSION

    def data_source(self, ds_id: str) -> DataSourceSpec:
        for ds in self.data_sources:
            if ds.id == ds_id:
                return ds
        raise SpecError(f"unknown data_source id: {ds_id!r}")


def _resolve_map_axes(
    ctx: str,
    ds: DataSourceSpec,
    latitude: EncodingRef | None,
    longitude: EncodingRef | None,
) -> tuple[EncodingRef, EncodingRef]:
    """Settle a map's two axes, inferring them from the data when not given.

    Coordinates are averaged, never summed. A caller who explicitly asks for
    ``Sum`` gets an error rather than a map with one mark somewhere in the
    Atlantic, because summing latitudes is never what anyone means.
    """
    from ..compiler.fields import GEO_AGGREGATION, GEO_LATITUDE, GEO_LONGITUDE

    fmap = ds.field_map()

    def infer(role: str, axis: str) -> EncodingRef:
        found = [f.name for f in ds.fields if f.semantic_role == role]
        _require(
            bool(found),
            f"{ctx}: template 'map' needs a {axis} field. None was given and none could "
            f"be inferred from data source {ds.id!r}. Either name a column "
            f"{'Latitude' if axis == 'latitude' else 'Longitude'}, or set "
            f"'{axis}' explicitly.",
        )
        _require(
            len(found) == 1,
            f"{ctx}: data source {ds.id!r} has more than one {axis} column ({sorted(found)}); "
            f"set '{axis}' explicitly so the choice is not guessed.",
        )
        return EncodingRef(field=found[0], aggregation=GEO_AGGREGATION)

    resolved: list[EncodingRef] = []
    for ref, role, axis in (
        (latitude, GEO_LATITUDE, "latitude"),
        (longitude, GEO_LONGITUDE, "longitude"),
    ):
        if ref is None:
            resolved.append(infer(role, axis))
            continue
        fld = fmap[ref.field]
        _require(
            fld.datatype in ("real", "integer"),
            f"{ctx}.{axis}: {ref.field!r} is {fld.datatype}, but a coordinate must be "
            f"numeric. Tableau plots nothing for a text coordinate.",
        )
        _require(
            ref.aggregation in ("None", GEO_AGGREGATION),
            f"{ctx}.{axis}: coordinates are averaged, not aggregated with "
            f"{ref.aggregation!r}. Summing a latitude places every mark at one "
            f"meaningless point. Use {GEO_AGGREGATION!r} or omit the aggregation.",
        )
        resolved.append(EncodingRef(field=ref.field, aggregation=GEO_AGGREGATION))

    lat, lon = resolved
    _require(
        lat.field != lon.field,
        f"{ctx}: latitude and longitude are both {lat.field!r}; a map needs two "
        f"different coordinate columns.",
    )
    return lat, lon


def _mark_requirements(template: str) -> tuple[bool, bool]:
    """(requires_rows, requires_columns) for a template."""
    return {
        "bar": (True, True),
        "line": (True, True),
        "text_table": (True, False),
        "heatmap": (True, True),
        "scatter": (True, True),
        "circle": (True, True),
        # A map's axes are its coordinates, which the compiler supplies. Asking
        # for rows/columns as well would be asking for a second pair of axes.
        "map": (False, False),
    }[template]


def parse_spec(raw: dict[str, Any]) -> WorkbookSpec:
    """Parse and semantically validate an authoring specification.

    Raises SpecError with an actionable message on the first problem found.
    """
    _require(
        isinstance(raw, dict),
        f"specification must be a JSON object, got {type(raw).__name__}",
    )

    unknown = set(raw) - set(TOP_LEVEL_KEYS)
    _require(not unknown, f"unknown top-level keys: {sorted(unknown)}")

    # Resolved before anything that takes a path, because it is the anchor they
    # are all measured from. None means "every path must be absolute"; a relative
    # path then fails with a message naming this key rather than silently
    # resolving against whatever directory the MCP client was launched in.
    base_raw = raw.get("base_dir")
    if base_raw is None:
        base_dir = default_base_dir()
    else:
        _require(
            isinstance(base_raw, str),
            f"'base_dir' must be a string, got {type(base_raw).__name__}",
        )
        try:
            base_dir = resolve_base_dir(base_raw)
        except PathSecurityError as exc:
            raise SpecError(f"base_dir: {exc}") from exc

    version = raw.get("spec_version", SPEC_VERSION)
    _require(
        version == SPEC_VERSION,
        f"unsupported spec_version {version!r}; this server implements {SPEC_VERSION!r}",
    )

    wb = raw.get("workbook") or {}
    _require(isinstance(wb, dict), f"'workbook' must be an object, got {type(wb).__name__}")
    unknown = set(wb) - set(WORKBOOK_KEYS)
    _require(not unknown, f"workbook: unknown keys {sorted(unknown)}")
    wb_name = _check_name(wb.get("name", ""), "workbook.name")
    # Previously str()-coerced, which quietly turned {"description": {"a": 1}}
    # into the literal text "{'a': 1}" in the published workbook's metadata.
    wb_desc = (_check_text(wb.get("description"), "workbook.description") or "").strip()

    # ---- data sources -----------------------------------------------------
    raw_ds = _optional_list(raw, "data_sources", "'data_sources'")
    _require(bool(raw_ds), "'data_sources' must be a non-empty array")
    data_sources: list[DataSourceSpec] = []
    seen_ds: set[str] = set()
    for i, d in enumerate(raw_ds):
        ctx = f"data_sources[{i}]"
        _require(isinstance(d, dict), f"{ctx} must be an object, got {type(d).__name__}")
        unknown = set(d) - set(DATA_SOURCE_KEYS)
        _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
        ds_id = _check_id(d.get("id", ""), f"{ctx}.id")
        _require(ds_id not in seen_ds, f"{ctx}: duplicate data source id {ds_id!r}")
        seen_ds.add(ds_id)
        ds_type = d.get("type", "csv")
        _require(ds_type == "csv", f"{ctx}: only type 'csv' is supported in v{SPEC_VERSION}")
        path = resolve_input_file(d.get("path", ""), must_suffix=".csv", base_dir=base_dir)
        data_sources.append(DataSourceSpec(id=ds_id, path=path, fields=infer_fields(path)))

    ds_by_id = {d.id: d for d in data_sources}

    # ---- calculated fields ------------------------------------------------
    for i, c in enumerate(_optional_list(raw, "calculated_fields", "'calculated_fields'")):
        ctx = f"calculated_fields[{i}]"
        _require(isinstance(c, dict), f"{ctx} must be an object, got {type(c).__name__}")
        unknown = set(c) - set(CALCULATED_FIELD_KEYS)
        _require(not unknown, f"{ctx}: unknown keys {sorted(unknown)}")
        name = _check_name(c.get("name", ""), f"{ctx}.name")
        ds_id = c.get("data_source", "")
        _require(
            ds_id in ds_by_id,
            f"{ctx}: unknown data_source {ds_id!r}; declared ids are {sorted(ds_by_id)}",
        )
        formula = c.get("formula", "")
        _require(
            isinstance(formula, str) and formula.strip(),
            f"{ctx}.formula must be a non-empty string, got {formula!r}",
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
    raw_ws = _optional_list(raw, "worksheets", "'worksheets'")
    _require(bool(raw_ws), "'worksheets' must be a non-empty array")
    worksheets: list[Worksheet] = []
    seen_ws: set[str] = set()

    for i, w in enumerate(raw_ws):
        ctx = f"worksheets[{i}]"
        _require(isinstance(w, dict), f"{ctx} must be an object, got {type(w).__name__}")
        unknown = set(w) - set(WORKSHEET_KEYS)
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
        _require(
            ds_id in ds_by_id,
            f"{ctx}: unknown data_source {ds_id!r}; declared ids are {sorted(ds_by_id)}",
        )
        ds = ds_by_id[ds_id]
        fmap = ds.field_map()

        def _refs(key: str, _w: dict = w, ws_ctx: str = ctx) -> list[EncodingRef]:
            vals = _optional_list(_w, key, f"{ws_ctx}.{key}")
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
        latitude = _ref("latitude")
        longitude = _ref("longitude")

        filters = _optional_list(w, "filters", f"{ctx}.filters")
        for j, f in enumerate(filters):
            _require(
                isinstance(f, str),
                f"{ctx}.filters[{j}] must be a field name string, got {f!r}",
            )

        # every referenced field must exist in the worksheet's data source
        for label_, refs in (
            ("rows", rows),
            ("columns", columns),
            ("detail", detail),
            ("tooltips", tooltips),
            ("color", [color] if color else []),
            ("size", [size] if size else []),
            ("label", [label] if label else []),
            ("latitude", [latitude] if latitude else []),
            ("longitude", [longitude] if longitude else []),
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
            # The only filter this version compiles is a categorical one: an
            # enumerated "select the values you want" card. Handed a measure it
            # emitted <filter class="categorical" column="...[none:Score:qk]">
            # over a QUANTITATIVE column instance - a card offering to tick every
            # distinct number in the column. Tableau does not reject it, so the
            # nonsense reached the published viz. A measure needs a range filter,
            # which is not generated (capabilities.py: categorical_filters only).
            fld = fmap[f]
            _require(
                not fld.is_measure,
                f"{ctx}.filters: {f!r} is a measure ({fld.datatype}), and only categorical "
                f"filters are generated - a value-picker over a continuous number is not a "
                f"usable filter card. Filter on a dimension instead, or add a "
                f"calculated_field that bands {f!r} into labels and filter on that.",
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

        title = _check_text(w.get("title"), f"{ctx}.title")
        subtitle = _check_text(w.get("subtitle"), f"{ctx}.subtitle")

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

        if template == "map":
            latitude, longitude = _resolve_map_axes(ctx, ds, latitude, longitude)
            # Without a grouping key every row averages into ONE mark, and a map
            # with a single dot in the middle of the data looks like a rendering
            # bug rather than a missing field. Tableau itself avoids this by
            # dropping the geographic dimension onto Detail automatically.
            grouping = [r for r in (*detail, color, label) if r and not fmap[r.field].is_measure]
            _require(
                bool(grouping),
                f"{ctx}: a 'map' needs at least one dimension on 'detail', 'color' or "
                f"'label' to place one mark per location. Without one, Tableau averages "
                f"every row into a single point. Put the location's identifying field "
                f"(a site or city name) on 'detail'.",
            )
        else:
            for key, ref in (("latitude", latitude), ("longitude", longitude)):
                _require(
                    ref is None,
                    f"{ctx}.{key} is only valid for the 'map' template, not {template!r}",
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
                title=title,
                subtitle=subtitle,
                fit=fit,
                latitude=latitude,
                longitude=longitude,
            )
        )

    # ---- dashboards -------------------------------------------------------
    # VERIFIED against Tableau Public 2026.2.0 — see the Dashboard docstring.
    raw_db = _optional_list(raw, "dashboards", "'dashboards'")
    dashboards: list[Dashboard] = []
    seen_db: set[str] = set()

    for i, d in enumerate(raw_db):
        ctx = f"dashboards[{i}]"
        _require(isinstance(d, dict), f"{ctx} must be an object, got {type(d).__name__}")
        unknown = set(d) - set(DASHBOARD_KEYS)
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
                f"{ctx}.title must be a non-empty string, got {title!r}",
            )
            _require(
                len(title) <= DASHBOARD_TITLE_MAX,
                f"{ctx}.title must be {DASHBOARD_TITLE_MAX} characters or fewer, "
                f"got {len(title)}",
            )

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
                f"{ctx}.{key} must be an integer number of pixels, got {value!r}",
            )
            _require(
                DASHBOARD_MIN_PX <= value <= DASHBOARD_MAX_PX,
                f"{ctx}.{key} must be between {DASHBOARD_MIN_PX} and {DASHBOARD_MAX_PX} "
                f"pixels, got {value}",
            )

        raw_zones = _optional_list(d, "worksheets", f"{ctx}.worksheets")
        _require(
            bool(raw_zones),
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
    _require(isinstance(out, dict), f"'output' must be an object, got {type(out).__name__}")
    unknown = set(out) - set(OUTPUT_KEYS)
    _require(not unknown, f"output: unknown keys {sorted(unknown)}")
    _require("directory" in out, "output.directory is required")
    out_dir = resolve_output_dir(out["directory"], base_dir=base_dir)
    package = out.get("package_twbx", True)
    _require(
        isinstance(package, bool),
        f"output.package_twbx must be a boolean, got {package!r}",
    )

    return WorkbookSpec(
        name=wb_name,
        description=wb_desc,
        data_sources=data_sources,
        worksheets=worksheets,
        output_dir=out_dir,
        base_dir=base_dir,
        dashboards=dashboards,
        package_twbx=package,
    )


# ------------------------------------------------------- the published contract
#
# ``schemas/workbook-spec-v0.1.json`` is GENERATED from the function below, not
# hand-written beside it. That inversion is the whole point.
#
# The file used to be maintained by hand and nothing ever loaded it, so it drifted
# without anyone noticing: it set ``additionalProperties: false`` on worksheets
# while omitting ``fit`` -- a key parse_spec accepted, the compiler emitted, and
# CAPABILITY_BOUNDARY.md listed as verified. Any consumer validating against the
# advertised contract rejected a spec this server happily built.
#
# Two other resolutions were considered and rejected:
#
#   * Load the file and run it as parse_spec's first pass. The published file is
#     not inside the wheel (pyproject's hatch config packages only
#     src/tableau_public_authoring), so an installed server would raise
#     FileNotFoundError from its most load-bearing function - and skipping the
#     check when the file is missing is the silent-degradation bug this project
#     writes drift tests to prevent. Generating the schema in-process removes the
#     packaging question entirely: the contract ships as code.
#   * Run a jsonschema pass in front of the hand-written checks anyway. Every
#     structural rule here already produces a message naming the offending key,
#     its path and the accepted values; jsonschema produces "Additional properties
#     are not allowed ('bogus' was unexpected)" with no path. Those messages are
#     read by a model deciding how to fix its own spec, so replacing them is a
#     regression, and translating jsonschema errors back into them would mean
#     maintaining the same message table twice - the duplication this file exists
#     to remove.
#
# What enforces the contract instead is tests/unit/test_schema_contract.py, which
# fails if the published file is not exactly what this function emits, if any key
# set here diverges from the dataclasses parse_spec fills, or if the schema ever
# rejects a spec parse_spec accepts.


def _encoding_ref_array(description: str) -> dict[str, Any]:
    """An optional array-of-encodings shelf. ``null`` is accepted as "absent"."""
    return {
        "type": ["array", "null"],
        "description": description,
        "items": {"$ref": "#/$defs/encodingRef"},
    }


def spec_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for a v0.1 authoring specification.

    Derived from the constants and dataclasses above, so it cannot describe a
    template, aggregation, fit mode, key or bound that ``parse_spec`` does not
    implement. A fresh dict is built per call: callers (MCP tool schemas, test
    fixtures) mutate what they are given, and a shared module-level document
    would let one caller's edit leak into the published file.

    The schema is deliberately NECESSARY BUT NOT SUFFICIENT. It cannot express
    the cross-references parse_spec enforces -- that a field exists in its data
    source, that a filter names a dimension, that a map has a grouping key -- so
    a document that validates here can still be rejected on semantics. It must
    never be the other way round: anything parse_spec accepts must validate,
    which is what test_schema_contract.py's differential tests pin.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        # A relative $id: the canonical location depends on where this project is
        # hosted, and baking one account's URL into a generated artifact is both
        # wrong for forks and a needless identifier to carry around.
        "$id": f"workbook-spec-v{SPEC_VERSION}.json",
        "title": f"Tableau Public Authoring Specification v{SPEC_VERSION}",
        "description": (
            "Declarative description of a Tableau workbook to generate. Unknown "
            "properties are rejected everywhere. Generated from "
            "tableau_public_authoring.models.spec.spec_json_schema(); edit that "
            "function, never this file. Structural validation only - the server "
            "additionally checks cross-references, field existence and encoding "
            "compatibility, so a valid document here can still be rejected."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["workbook", "data_sources", "worksheets", "output"],
        "properties": {
            "spec_version": {"const": SPEC_VERSION, "default": SPEC_VERSION},
            "base_dir": {
                "type": ["string", "null"],
                "description": (
                    "Absolute directory that every RELATIVE path in this spec is "
                    "resolved against. Optional: paths may instead be absolute. A "
                    "relative path is also required to stay inside base_dir after "
                    "resolution, so it can address nothing outside it -- which is why "
                    "relative paths are accepted at all. Relative paths are never "
                    "resolved against the working directory, because an MCP server "
                    "inherits that from whichever client launched it."
                ),
            },
            "workbook": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {
                    "name": {"$ref": "#/$defs/displayName"},
                    "description": {"type": ["string", "null"]},
                },
            },
            "data_sources": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "path"],
                    "properties": {
                        "id": {"$ref": "#/$defs/identifier"},
                        "type": {"const": "csv", "default": "csv"},
                        "path": {"$ref": "#/$defs/filesystemPath"},
                    },
                },
            },
            "calculated_fields": {
                "type": ["array", "null"],
                "default": [],
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "data_source", "formula"],
                    "properties": {
                        "name": {"$ref": "#/$defs/displayName"},
                        "data_source": {"$ref": "#/$defs/identifier"},
                        "formula": {"type": "string", "minLength": 1},
                        "datatype": {"$ref": "#/$defs/datatype", "default": "string"},
                    },
                },
            },
            "worksheets": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "template", "data_source"],
                    "properties": {
                        "name": {"$ref": "#/$defs/displayName"},
                        "template": {"enum": list(SUPPORTED_TEMPLATES)},
                        "data_source": {"$ref": "#/$defs/identifier"},
                        "rows": _encoding_ref_array("Fields on the Rows shelf."),
                        "columns": _encoding_ref_array("Fields on the Columns shelf."),
                        "color": {"$ref": "#/$defs/encodingShelf"},
                        "size": {
                            "$ref": "#/$defs/encodingShelf",
                            "description": (
                                "Needs a measure or an aggregation; a bare dimension has "
                                "no magnitude to scale a mark by."
                            ),
                        },
                        "label": {"$ref": "#/$defs/encodingShelf"},
                        "detail": _encoding_ref_array(
                            "Tableau's Detail shelf. Each dimension listed here becomes a "
                            "grouping key, raising the mark count (e.g. one mark per site "
                            "instead of one per Color value). A field may appear at most "
                            "once."
                        ),
                        "tooltips": _encoding_ref_array(
                            "Fields shown on hover. A dimension here is promoted to the "
                            "Attribute aggregation automatically, because derivation "
                            "'None' renders the pill red and the sheet blank."
                        ),
                        "filters": {
                            "type": ["array", "null"],
                            "description": (
                                "Field names to expose as interactive filter cards. Only "
                                "CATEGORICAL (value-picker) filters are generated, so each "
                                "name must be a dimension; a measure is rejected because a "
                                "value picker over a continuous number is not a usable "
                                "card. Range filters are not generated."
                            ),
                            "items": {"type": "string", "minLength": 1},
                        },
                        "title": {"type": ["string", "null"]},
                        "subtitle": {"type": ["string", "null"]},
                        "fit": {
                            "enum": [*FIT_MODES, None],
                            "description": (
                                "How the viz fills the canvas. Omitted or null uses "
                                "Tableau's 'Standard' fit, which draws a small viz tucked "
                                "into the top-left corner."
                            ),
                        },
                        "latitude": {
                            "$ref": "#/$defs/encodingShelf",
                            "description": (
                                "Map only. The latitude column, placed on Rows. Inferred "
                                "from a column named Latitude/Lat when omitted. Always "
                                "averaged: summing coordinates collapses every mark onto "
                                "one point."
                            ),
                        },
                        "longitude": {
                            "$ref": "#/$defs/encodingShelf",
                            "description": (
                                "Map only. The longitude column, placed on Columns. "
                                "Inferred from a column named Longitude/Long/Lon/Lng when "
                                "omitted."
                            ),
                        },
                    },
                },
            },
            "dashboards": {
                "type": ["array", "null"],
                "default": [],
                "description": (
                    "VERIFIED against Tableau Public 2026.2.0: title, worksheet zones "
                    "and fixed sizing all render. Dashboard extras - filter cards, "
                    "colour legends, highlighters, parameter controls, images, floating "
                    "zones, device layouts and actions - are understood but not "
                    "generated. See docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "worksheets"],
                    "properties": {
                        "name": {
                            "$ref": "#/$defs/displayName",
                            "description": (
                                "Unique across dashboards, and distinct from every "
                                "worksheet name: both are registered in <windows> by name."
                            ),
                        },
                        "title": {
                            "type": ["string", "null"],
                            "minLength": 1,
                            "maxLength": DASHBOARD_TITLE_MAX,
                            "description": (
                                "Dashboard title. Emits both the title text and the title "
                                "card that gives it canvas space."
                            ),
                        },
                        "direction": {
                            "enum": list(DASHBOARD_DIRECTIONS),
                            "default": "vertical",
                            "description": (
                                "Flow direction of the single layout container holding "
                                "the worksheets."
                            ),
                        },
                        "sizing_mode": {
                            "enum": list(DASHBOARD_SIZING_MODES),
                            "default": "fixed",
                            "description": (
                                "'fixed' declares the pixel canvas below; 'automatic' "
                                "fits the window and forbids width/height."
                            ),
                        },
                        "width": {
                            "type": "integer",
                            "minimum": DASHBOARD_MIN_PX,
                            "maximum": DASHBOARD_MAX_PX,
                            "default": DASHBOARD_DEFAULT_WIDTH,
                            "description": (
                                "Canvas width in PIXELS. Only valid when sizing_mode is "
                                "'fixed'."
                            ),
                        },
                        "height": {
                            "type": "integer",
                            "minimum": DASHBOARD_MIN_PX,
                            "maximum": DASHBOARD_MAX_PX,
                            "default": DASHBOARD_DEFAULT_HEIGHT,
                            "description": (
                                "Canvas height in PIXELS. Only valid when sizing_mode is "
                                "'fixed'."
                            ),
                        },
                        "worksheets": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": DASHBOARD_MAX_ZONES,
                            "description": (
                                "Worksheets to place, in layout order. Each must exist "
                                "and may appear at most once per dashboard."
                            ),
                            "items": {"$ref": "#/$defs/dashboardZone"},
                        },
                    },
                },
            },
            "output": {
                "type": "object",
                "additionalProperties": False,
                "required": ["directory"],
                "properties": {
                    "directory": {"$ref": "#/$defs/filesystemPath"},
                    "package_twbx": {"type": "boolean", "default": True},
                },
            },
        },
        "$defs": {
            "identifier": {
                "type": "string",
                "pattern": _ID_RE.pattern,
                "description": "Lowercase alphanumeric/underscore, starting with a letter.",
            },
            "displayName": {
                "type": "string",
                "pattern": NAME_PATTERN_JSON,
                "description": (
                    "A caption shown in Tableau. Letters, digits, spaces and "
                    ". , - _ ( ) / & ' % : + # only, up to 120 characters. Surrounding "
                    "whitespace is allowed and trimmed by the server."
                ),
            },
            "filesystemPath": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "An absolute path, a '~' path the server expands, or a path "
                    "relative to the spec's 'base_dir'. Traversal segments ('..') and "
                    "null bytes are rejected; a relative path must additionally resolve "
                    "inside base_dir, and an input file must exist, be a regular file "
                    "and be under the size caps."
                ),
            },
            "datatype": {"enum": list(VALID_DATATYPES)},
            "aggregation": {"enum": list(AGGREGATIONS)},
            "dashboardZone": {
                "description": (
                    "A worksheet placed on a dashboard, referenced by exact worksheet "
                    "name -- the compiled zone has no id-based link, so a mismatched "
                    "name renders an empty box."
                ),
                "oneOf": [
                    {
                        "type": "string",
                        "minLength": 1,
                        "description": "Worksheet name, title shown",
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["worksheet"],
                        "properties": {
                            "worksheet": {"type": "string", "minLength": 1},
                            "show_title": {
                                "type": "boolean",
                                "default": True,
                                "description": (
                                    "false hides that worksheet's own title inside the "
                                    "dashboard."
                                ),
                            },
                        },
                    },
                ],
            },
            "encodingRef": {
                "oneOf": [
                    {
                        "type": "string",
                        "minLength": 1,
                        "description": "Field name, no aggregation",
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["field"],
                        "properties": {
                            "field": {"type": "string", "minLength": 1},
                            "aggregation": {
                                "$ref": "#/$defs/aggregation",
                                "default": "None",
                            },
                        },
                    },
                ],
            },
            "encodingShelf": {
                "description": (
                    "A single-value encoding shelf. null means the encoding is absent, "
                    "exactly as omitting the key does."
                ),
                "anyOf": [{"$ref": "#/$defs/encodingRef"}, {"type": "null"}],
            },
        },
    }
