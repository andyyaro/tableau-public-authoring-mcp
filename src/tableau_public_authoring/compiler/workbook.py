"""Tableau ``.twb`` XML compiler.

All XML is produced with :mod:`xml.etree.ElementTree` nodes. No markup is ever
built by string concatenation or substitution, which is what makes the compiler
immune to XML injection through user-supplied names and formulas (T1).

Node structures were derived from a real workbook produced by the installed
Tableau Public build (see docs/fixtures/REFERENCE_WORKBOOK_ANALYSIS.md). Version
metadata is pinned to that build.

The ``<dashboards>`` section was reverse-engineered from published workbooks at
document version 18.1 written by Tableau builds 2019.4.3-2023.1.0
(docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md), because the reference workbook
contains no dashboards. It has since been **verified**: generated dashboards open
in Tableau Public 2026.2.0 with their title, worksheets and fixed sizing intact,
and ``tests/live/test_dashboard.py`` re-checks it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..models.spec import Dashboard, EncodingRef, WorkbookSpec, Worksheet
from .fields import Field, bracket
from .ids import connection_name, datasource_name

# Pinned from the verified fixture: build 2026.2.0 (20262.26.0603.1643), doc 18.1
DOC_VERSION = "18.1"
SOURCE_BUILD = "2026.2.0 (20262.26.0603.1643)"
SOURCE_PLATFORM = "mac"

# Tableau's 'user' namespace, used for ui-* hints on group filters.
USER_NS = "http://www.tableausoftware.com/xml/user"
ET.register_namespace("user", USER_NS)

MARK_CLASS = {
    "bar": "Bar",
    "line": "Line",
    "text_table": "Text",
    "heatmap": "Square",
    "scatter": "Circle",
    "circle": "Circle",
    # A symbol map. The reference workbook's map sheets use "Shape" because they
    # encode a shape field; "Circle" is Tableau's own default for a plain symbol
    # map and needs no shape palette.
    "map": "Circle",
}

# Tableau's built-in background map service. Without a <mapsources> element the
# sheet still plots the coordinates, but on a blank white canvas with no
# coastline, which reads as a broken map rather than a map.
MAP_SOURCE = "Tableau"

# Canvas fit. Stored as <windows><window><viewpoint><zoom type=...>, AFTER <cards>.
# Absent  == Tableau's "Standard" fit, which renders a small viz in the top-left
# corner. Values observed in the reference workbook: fit-width and entire-view.
ZOOM_TYPE = {
    "standard": None,
    "fit_width": "fit-width",
    "fit_height": "fit-height",
    "entire_view": "entire-view",
}

# Defaults mirror the choices Tableau's own author made in the reference workbook:
# grid-shaped views get entire-view, everything else fit-width.
_DEFAULT_FIT = {
    "bar": "fit_width",
    "line": "fit_width",
    "scatter": "fit_width",
    "circle": "fit_width",
    "heatmap": "entire_view",
    "text_table": "entire_view",
    # A map that does not fill its canvas is a postage stamp of coastline.
    "map": "entire_view",
}


def default_fit(template: str) -> str:
    return _DEFAULT_FIT.get(template, "fit_width")


_DERIVATION_PREFIX = {
    "None": "none",
    "Sum": "sum",
    "Avg": "avg",
    "Min": "min",
    "Max": "max",
    "Count": "cnt",
    "CountD": "ctd",
    "Attribute": "attr",
}

_TYPE_SUFFIX = {"nominal": "nk", "quantitative": "qk", "ordinal": "ok"}

# ---------------------------------------------------------------- dashboards
# EXPERIMENTAL / UNVERIFIED. See _build_dashboard and models.spec.Dashboard.
#
# Zone geometry is a 0..100000 normalised grid, ABSOLUTE within a dashboard (not
# parent-relative), independently normalised on each axis against the canvas
# extent. This is NOT pixels: the <size> element's min/max bounds and a zone's
# 'fixed-size' are pixels, the x/y/w/h below are grid units. Mixing them puts
# zones off by ~two orders of magnitude, so the two unit systems are kept in
# separately named constants. Evidence: DASHBOARD_FIXTURE_ANALYSIS.md §4.1.
ZONE_GRID = 100000

# Grid height reserved for the dashboard-title card. 6000/100000 of an 800px
# canvas is 48px, matching the fixture skeleton (§9).
TITLE_ZONE_GRID_HEIGHT = 6000

ZONE_MARGIN = "4"
ROOT_ZONE_MARGIN = "8"


class CompileError(RuntimeError):
    """Raised when a specification cannot be compiled into valid workbook XML."""


class _ZoneIds:
    """Sequential zone-id allocator, one instance per dashboard.

    Tableau's zone ids are small unique integers scoped to a dashboard, not the
    28-character base-36 identifiers ``compiler/ids.py`` produces for data
    sources (§4.5). A counter over a deterministic tree walk satisfies both
    Tableau's format and the project's byte-determinism guarantee.
    """

    def __init__(self) -> None:
        self._next = 1

    def take(self) -> str:
        value = self._next
        self._next += 1
        return str(value)


def _tile(count: int, total: int, offset: int) -> list[tuple[int, int]]:
    """Split ``total`` grid units into ``count`` contiguous spans from ``offset``.

    Siblings inside a layout container must tile their parent's extent exactly -
    no gap, no overlap (§4.1). Integer division alone does not sum back to the
    total for most counts, so the final span absorbs the rounding remainder.
    Returns ``(start, size)`` pairs.
    """
    if count <= 0:
        return []
    span = total // count
    spans: list[tuple[int, int]] = []
    pos = offset
    for i in range(count):
        size = total - (pos - offset) if i == count - 1 else span
        spans.append((pos, size))
        pos += size
    return spans


def _zone_style(zone: ET.Element, margin: str) -> None:
    """Append the near-universal border/margin quartet as the zone's LAST child.

    ``zone-style`` is the final child in 100% of the fixture zones that have one;
    nested ``<zone>`` children always precede it (§4.2/§4.6).
    """
    style = ET.SubElement(zone, "zone-style")
    for attr, value in (
        ("border-color", "#000000"),
        ("border-style", "none"),
        ("border-width", "0"),
        ("margin", margin),
    ):
        ET.SubElement(style, "format", {"attr": attr, "value": value})


def _instance_type(field: Field, aggregation: str) -> str:
    """The resulting shelf type once an aggregation is applied."""
    if aggregation in ("Sum", "Avg", "Min", "Max", "Count", "CountD"):
        return "quantitative"
    if aggregation == "Attribute":
        return field.type if field.type != "quantitative" else "nominal"
    return field.type


def _instance_name(field: Field, aggregation: str) -> str:
    """Build a ``[sum:Field:qk]``-style column-instance name."""
    prefix = _DERIVATION_PREFIX[aggregation]
    itype = _instance_type(field, aggregation)
    suffix = _TYPE_SUFFIX[itype]
    base = field.calc_name if field.is_calculated and field.calc_name else field.name
    # The whole instance name is one identifier, so the ']' escape applies to the
    # composed string, not to `base` alone.
    return bracket(f"{prefix}:{base}:{suffix}")


def _column_attrs(f: Field) -> dict[str, str]:
    """Attributes for a <column> declaration, in both the data source and a view.

    A geographic column carries two extras, copied from a published workbook that
    renders a real map:
        <column aggregation="Avg" datatype="real" name="[Latitude]" role="measure"
                semantic-role="[Geographical].[Latitude]" type="quantitative" />
    The semantic-role is what makes Tableau treat the number as a coordinate at
    all; without it the field is an ordinary measure and the sheet draws a scatter
    plot with no basemap. The aggregation override matters just as much: Tableau's
    default is Sum, and a summed latitude puts every mark at one nonsense point.
    """
    attrs = {
        "datatype": f.datatype,
        "name": f.reference_name,
        "role": f.role,
        "type": f.type,
    }
    if f.semantic_role:
        attrs["semantic-role"] = f.semantic_role
        attrs["aggregation"] = f.default_aggregation
    if f.is_calculated:
        attrs["caption"] = f.name
    return attrs


def _qualified(ds_name: str, instance: str) -> str:
    """Fully-qualified shelf reference: ``[federated.x].[sum:F:qk]``."""
    return f"[{ds_name}].{instance}"


class WorkbookCompiler:
    """Compiles a validated :class:`WorkbookSpec` into ``.twb`` XML."""

    def __init__(self, spec: WorkbookSpec) -> None:
        self.spec = spec
        self._ds_names: dict[str, str] = {
            ds.id: datasource_name(spec.name, ds.id) for ds in spec.data_sources
        }
        self._conn_names: dict[str, str] = {
            ds.id: connection_name(spec.name, ds.id) for ds in spec.data_sources
        }

    # ------------------------------------------------------------------ data
    def _build_datasource(self, ds_id: str, data_dir_ref: str) -> ET.Element:
        ds = self.spec.data_source(ds_id)
        # Tableau resolves both paths emitted below RELATIVE TO THE WORKBOOK FILE:
        # the archive root inside a .twbx, the containing directory for a bare
        # .twb. `data_dir_ref` is the root the build pipeline has actually
        # materialised; each data source owns a subdirectory under it so two
        # sources can never collide on a file name.
        #
        # This parameter used to be named `_unused` and was ignored: the method
        # recomputed `data_dir_for(ds_id)` and so hardcoded the .twbx-internal
        # layout into every file it wrote. A bare .twb therefore pointed at a
        # `Data/<id>/` directory that only exists inside the package - verified on
        # a real artifact (output/TplLine.twb says directory="Data/sites" while
        # output/Data/ does not exist), so a standalone .twb could not find its
        # data at all.
        data_dir = f"{data_dir_ref}/{ds_id}"
        ds_name = self._ds_names[ds_id]
        conn_name = self._conn_names[ds_id]
        csv_file = ds.path.name
        table_id = csv_file.rsplit(".", 1)[0]

        node = ET.Element(
            "datasource",
            {"caption": ds.id, "inline": "true", "name": ds_name, "version": DOC_VERSION},
        )
        conn = ET.SubElement(node, "connection", {"class": "federated"})

        named = ET.SubElement(conn, "named-connections")
        nc = ET.SubElement(named, "named-connection", {"caption": ds.id, "name": conn_name})
        ET.SubElement(
            nc,
            "connection",
            {
                "class": "textscan",
                "directory": data_dir,
                "filename": csv_file,
                "password": "",
                "server": "",
                "workgroup-auth-mode": "as-is",
            },
        )

        rel = ET.SubElement(
            conn,
            "relation",
            {
                "connection": conn_name,
                "name": csv_file,
                "table": f"[{table_id}#csv]",
                "type": "table",
            },
        )
        cols = ET.SubElement(
            rel,
            "columns",
            {
                "character-set": "UTF-8",
                "header": "yes",
                "locale": "en_US",
                "separator": ",",
            },
        )
        for f in ds.fields:
            if f.is_calculated:
                continue
            ET.SubElement(
                cols,
                "column",
                {"datatype": f.datatype, "name": f.name, "ordinal": str(f.ordinal)},
            )

        # metadata-records describe each physical column to Tableau's catalog
        meta = ET.SubElement(conn, "metadata-records")
        for f in ds.fields:
            if f.is_calculated:
                continue
            rec = ET.SubElement(meta, "metadata-record", {"class": "column"})
            ET.SubElement(rec, "remote-name").text = f.name
            ET.SubElement(rec, "remote-type").text = _remote_type(f.datatype)
            ET.SubElement(rec, "local-name").text = f.bracketed
            ET.SubElement(rec, "parent-name").text = f"[{csv_file}]"
            ET.SubElement(rec, "remote-alias").text = f.name
            ET.SubElement(rec, "ordinal").text = str(f.ordinal)
            ET.SubElement(rec, "local-type").text = f.datatype
            ET.SubElement(rec, "aggregation").text = "Sum" if f.is_measure else "Count"
            ET.SubElement(rec, "contains-null").text = "true"
            attrs = ET.SubElement(rec, "attributes")
            for k, v in (
                ("DebugRemoteType", f'"{_remote_type(f.datatype)}"'),
                ("DebugWrapperType", '"0"'),
            ):
                a = ET.SubElement(attrs, "attribute", {"datatype": "string", "name": k})
                a.text = v

        ET.SubElement(node, "aliases", {"enabled": "yes"})

        # explicit column declarations (roles, and calculated-field formulas)
        for f in ds.fields:
            col = ET.SubElement(node, "column", _column_attrs(f))
            if f.is_calculated and f.formula:
                # ElementTree escapes the formula automatically (T1).
                ET.SubElement(col, "calculation", {"class": "tableau", "formula": f.formula})

        # ---- extract (REQUIRED by Tableau Public) --------------------------
        # Tableau Public refuses to save/publish a workbook whose data source is
        # not an extract (Error Code 3C242D89). Verified empirically.
        # Only count/enabled/units are declared for <extract> in the loader's
        # DTD. Tableau writes 'object-id' and 'user-specific' in its own files,
        # but rejects them on load:
        #   attribute 'object-id' is not declared for element 'extract'
        ext = ET.SubElement(
            node,
            "extract",
            {"count": "-1", "enabled": "true", "units": "records"},
        )
        econn = ET.SubElement(
            ext,
            "connection",
            {
                "access_mode": "readonly",
                "author-locale": "en_US",
                "class": "hyper",
                "dbname": f"{data_dir}/{ds.hyper_name}",
                "default-settings": "hyper",
                "schema": "Extract",
                "sslmode": "",
                "tablename": "Extract",
                "update-time": "",
            },
        )
        ET.SubElement(
            econn,
            "relation",
            {"name": "Extract", "table": "[Extract].[Extract]", "type": "table"},
        )
        emeta = ET.SubElement(econn, "metadata-records")
        for f in ds.fields:
            if f.is_calculated:
                continue
            rec = ET.SubElement(emeta, "metadata-record", {"class": "column"})
            ET.SubElement(rec, "remote-name").text = f.name
            ET.SubElement(rec, "remote-type").text = _remote_type(f.datatype)
            ET.SubElement(rec, "local-name").text = f.bracketed
            ET.SubElement(rec, "parent-name").text = "[Extract]"
            ET.SubElement(rec, "remote-alias").text = f.name
            ET.SubElement(rec, "ordinal").text = str(f.ordinal)
            ET.SubElement(rec, "family").text = csv_file
            ET.SubElement(rec, "local-type").text = f.datatype
            ET.SubElement(rec, "aggregation").text = "Sum" if f.is_measure else "Count"
            ET.SubElement(rec, "approx-count").text = str(ds.row_count)
            ET.SubElement(rec, "contains-null").text = "true"

        # dim-percentage / measure-percentage are REQUIRED by the loader's DTD.
        # Verified empirically: omitting them raises
        #   Error: missing required attribute 'dim-percentage'
        ET.SubElement(
            node,
            "layout",
            {
                "dim-ordering": "alphabetic",
                "dim-percentage": "0.5",
                "measure-ordering": "alphabetic",
                "measure-percentage": "0.4",
                "show-structure": "true",
            },
        )
        # NOTE: <object-graph> is deliberately NOT emitted. Tableau writes it in
        # its own files, but the loader's DTD rejects it inside <datasource>
        # ("no declaration found for element 'object-graph'"). It is optional
        # catalog metadata, so omitting it is both valid and simpler.
        return node

    # ------------------------------------------------------------- worksheet
    def _build_worksheet(self, ws: Worksheet) -> ET.Element:
        ds = self.spec.data_source(ws.data_source)
        ds_name = self._ds_names[ws.data_source]
        fmap = ds.field_map()

        node = ET.Element("worksheet", {"name": ws.name})

        if ws.title or ws.subtitle:
            lo = ET.SubElement(node, "layout-options")
            title = ET.SubElement(lo, "title")
            ft = ET.SubElement(title, "formatted-text")
            if ws.title:
                run = ET.SubElement(ft, "run", {"bold": "true", "fontsize": "15"})
                run.text = ws.title
            if ws.subtitle:
                if ws.title:
                    ET.SubElement(ft, "run").text = "\n"
                sub = ET.SubElement(ft, "run", {"fontcolor": "#898989", "fontsize": "10"})
                sub.text = ws.subtitle

        table = ET.SubElement(node, "table")
        view = ET.SubElement(table, "view")
        dss = ET.SubElement(view, "datasources")
        ET.SubElement(dss, "datasource", {"caption": ds.id, "name": ds_name})

        # <mapsources> sits between <datasources> and <datasource-dependencies>.
        # Verified against a published map sheet (docs/fixtures/MAP_FIXTURE_ANALYSIS.md).
        if ws.template == "map":
            msrc = ET.SubElement(view, "mapsources")
            ET.SubElement(msrc, "mapsource", {"name": MAP_SOURCE})

        deps = ET.SubElement(view, "datasource-dependencies", {"datasource": ds_name})

        # Collect every (field, aggregation) pair this sheet references.
        used: list[tuple[Field, str]] = []
        seen_instances: set[str] = set()

        def use(ref: EncodingRef | None) -> str | None:
            if ref is None:
                return None
            fld = fmap[ref.field]
            inst = _instance_name(fld, ref.aggregation)
            if inst not in seen_instances:
                seen_instances.add(inst)
                used.append((fld, ref.aggregation))
            return _qualified(ds_name, inst)

        # A map's axes ARE its coordinates: latitude on rows, longitude on cols.
        # That assignment is fixed by the projection, not a caller preference -
        # swapping them plots the transpose of the world. parse_spec guarantees
        # both are present and averaged for this template.
        if ws.template == "map":
            row_refs = [use(ws.latitude)]
            col_refs = [use(ws.longitude)]
        else:
            row_refs = [use(r) for r in ws.rows]
            col_refs = [use(c) for c in ws.columns]
        color_ref = use(ws.color)
        size_ref = use(ws.size)
        label_ref = use(ws.label)

        # The Detail shelf. Refs are passed through UNCHANGED - deliberately the
        # opposite of _tooltip_ref below. A dimension on Detail keeps derivation
        # "None" (``[none:Field:nk]``) because it *is* the grouping key: it is
        # what raises the mark count from one-per-Color-value to one-per-entity.
        # Promoting it to Attribute would preserve the existing level of detail,
        # which is precisely what Detail exists to change. A measure on Detail
        # aggregates normally, using whatever aggregation the spec names.
        detail_refs = [use(d) for d in ws.detail]

        # A dimension dropped on Tooltip must use the Attribute derivation
        # (``[attr:Field:nk]``). With derivation="None" Tableau treats it as a
        # level-of-detail field, cannot resolve the reference, and renders the
        # pill red with a blank canvas. Verified against the reference workbook,
        # which uses attr: for every tooltip dimension.
        def _tooltip_ref(t: EncodingRef) -> EncodingRef:
            fld = fmap[t.field]
            if not fld.is_measure and t.aggregation == "None":
                return EncodingRef(field=t.field, aggregation="Attribute")
            return t

        tooltip_refs = [use(_tooltip_ref(t)) for t in ws.tooltips]

        # Every filter this compiler emits is categorical: class="categorical"
        # over a `level-members` groupfilter, plus a checkdropdown card. That is
        # the ONE filter shape verified against a workbook Tableau actually
        # opened, and it is only meaningful over discrete values.
        #
        # A measure filter used to reach this code and compile to a categorical
        # filter over a QUANTITATIVE instance:
        #   <filter class="categorical" column="[federated.…].[none:Value:qk]">
        # Tableau loads that file and draws a checkbox list over a continuous
        # field - a nonsense card, with no error anywhere. Refusing is the safer
        # trade: a wrong filter fails silently in front of the user, a
        # CompileError fails loudly in front of the caller, who can still express
        # the intent with a calculated field. Emitting class="quantitative"
        # instead would mean guessing at a content model no fixture in this
        # project evidences, and mis-modelled children are exactly what the
        # loader rejects outright (tests/unit/test_dtd_regression.py).
        #
        # models/spec.py rejects this at layer 1 as well. The duplication is
        # deliberate and matches how the zone->worksheet reference is checked in
        # both layers: WorkbookCompiler is public and takes a WorkbookSpec built
        # any way at all, and the one thing it must never do is emit markup it
        # already knows is wrong.
        for fname in ws.filters:
            fld = fmap[fname]
            if _instance_type(fld, "None") == "quantitative":
                raise CompileError(
                    f"worksheet {ws.name!r}: cannot filter on {fname!r}. This compiler emits "
                    f"categorical (level-members) filters over a field's discrete values, and "
                    f"{fname!r} is a {fld.datatype} measure - the filter would render as a "
                    f"checkbox list over a continuous field, which Tableau accepts and draws "
                    f"as a nonsense card. Filter on a dimension instead, or add a "
                    f"calculated_field that buckets {fname!r} into named ranges (e.g. "
                    f'IF [{fname}] > 100 THEN "high" ELSE "low" END) and filter on that.'
                )

        filter_refs = [use(EncodingRef(field=f, aggregation="None")) for f in ws.filters]

        # <column> declarations for every distinct field touched by this sheet
        declared: set[str] = set()
        for fld, _agg in used:
            if fld.reference_name in declared:
                continue
            declared.add(fld.reference_name)
            c = ET.SubElement(deps, "column", _column_attrs(fld))
            if fld.is_calculated and fld.formula:
                ET.SubElement(c, "calculation", {"class": "tableau", "formula": fld.formula})

        # <column-instance> for each distinct (field, aggregation)
        for fld, agg in used:
            ET.SubElement(
                deps,
                "column-instance",
                {
                    "column": fld.reference_name,
                    "derivation": agg,
                    "name": _instance_name(fld, agg),
                    "pivot": "key",
                    "type": _instance_type(fld, agg),
                },
            )

        # Filters and slices live inside <view>, NOT <table>. Verified from the
        # reference workbook and confirmed by the loader's content model:
        #   (view,style,panes,mark-layout?,rows,cols,...)
        # <view> order is: datasources, datasource-dependencies, filter*, slices?, aggregation
        fmap_ws = fmap
        for fld_ref, fname in zip(filter_refs, ws.filters, strict=True):
            if fld_ref is None:
                continue
            filt = ET.SubElement(view, "filter", {"class": "categorical", "column": fld_ref})
            inst = _instance_name(fmap_ws[fname], "None")
            grp = ET.SubElement(filt, "groupfilter", {"function": "level-members", "level": inst})
            # These attributes are namespaced under the Tableau 'user' namespace.
            grp.set(f"{{{USER_NS}}}ui-enumeration", "all")
            grp.set(f"{{{USER_NS}}}ui-marker", "enumerate")

        if ws.filters:
            slices = ET.SubElement(view, "slices")
            for fr in filter_refs:
                if fr:
                    ET.SubElement(slices, "column").text = fr

        ET.SubElement(view, "aggregation", {"value": "true"})

        # <style> is REQUIRED between <view> and <panes> by the loader's DTD.
        ET.SubElement(table, "style")

        panes = ET.SubElement(table, "panes")
        pane = ET.SubElement(
            panes, "pane", {"selection-relaxation-option": "selection-relaxation-allow"}
        )
        pview = ET.SubElement(pane, "view")
        ET.SubElement(pview, "breakdown", {"value": "auto"})
        ET.SubElement(pane, "mark", {"class": MARK_CLASS[ws.template]})

        enc = ET.SubElement(pane, "encodings")
        if color_ref:
            ET.SubElement(enc, "color", {"column": color_ref})
        if size_ref:
            ET.SubElement(enc, "size", {"column": size_ref})
        if label_ref:
            ET.SubElement(enc, "text", {"column": label_ref})
        # Tableau serialises the Detail shelf as <lod> inside <encodings>, next
        # to <color>/<size>/<text>/<tooltip>. Verified in the reference workbook,
        # whose heat-map sheets carry
        #   <lod column='[federated.…].[none:Site ID:nk]' />
        # between <color> and <tooltip> (docs/fixtures/REFERENCE_WORKBOOK_ANALYSIS.md).
        # Sibling order inside <encodings> varies across those sheets, so this
        # position is a convention, not a constraint.
        for d in detail_refs:
            if d:
                ET.SubElement(enc, "lod", {"column": d})
        for t in tooltip_refs:
            if t:
                ET.SubElement(enc, "tooltip", {"column": t})

        # A text table needs a MEASURE on the Text encoding to render anything.
        #
        # The guard used to be `not label_ref and col_refs`, which keyed off the
        # wrong shelf: _mark_requirements("text_table") is (rows=True,
        # cols=False), so the canonical text table has no columns at all and the
        # fallback never fired. Verified - rows=["Site", {"field": "Value",
        # "aggregation": "Sum"}] compiled to <encodings /> with nothing on Text,
        # plus mark-labels-show=true labelling nothing. And when `columns` WAS
        # present it took col_refs[0] blindly, which is a dimension whenever the
        # caller put one there.
        #
        # Rows are searched first because that is the shelf the template
        # requires; a quantitative column-instance is exactly "an aggregated
        # measure", so SUM(Value) and COUNT(Site) both qualify while a bare
        # dimension does not.
        text_fallback: str | None = None
        if ws.template == "text_table" and not label_ref:
            for ref in (*ws.rows, *ws.columns):
                fld = fmap[ref.field]
                if _instance_type(fld, ref.aggregation) == "quantitative":
                    text_fallback = _qualified(ds_name, _instance_name(fld, ref.aggregation))
                    break
            if text_fallback:
                ET.SubElement(enc, "text", {"column": text_fallback})

        # <style> is the LAST child of <pane>. The loader's content model is
        #   (view, mark, mark-sizing?, encodings?, label-data*, dropline?,
        #    trendline?, reference-line, customized-tooltip, customized-label, style)
        # Emitting it before <encodings> yields:
        #   element 'encodings' is not allowed for content model ...
        # Placing a field on Label is also not enough on its own: without
        # mark-labels-show Tableau keeps labels hidden, so the pill appears on the
        # Marks card but no text is drawn.
        #
        # The converse is just as useless and used to happen on every text table
        # with no measure anywhere: labels switched on with nothing on Text to
        # draw. The rule is now emitted only where something can actually be
        # labelled - a heatmap keeps it unconditionally because its Color measure
        # is what gets labelled.
        if label_ref or text_fallback or ws.template == "heatmap":
            pstyle = ET.SubElement(pane, "style")
            rule = ET.SubElement(pstyle, "style-rule", {"element": "mark"})
            ET.SubElement(rule, "format", {"attr": "mark-labels-show", "value": "true"})
            ET.SubElement(rule, "format", {"attr": "mark-labels-cull", "value": "true"})

        # <rows>/<cols> follow <panes> in the loader's content model.
        ET.SubElement(table, "rows").text = " / ".join(r for r in row_refs if r)
        ET.SubElement(table, "cols").text = " / ".join(c for c in col_refs if c)

        return node

    # ------------------------------------------------------------- dashboard
    def _build_dashboard(self, dash: Dashboard) -> ET.Element:
        """Compile one dashboard. **EXPERIMENTAL / UNVERIFIED.**

        The structure below is reverse-engineered from published fixtures at
        document version 18.1 (docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md). No
        fixture written by the target build 2026.2.0 was available and **no
        generated dashboard has ever been opened in Tableau**, so this may fail
        to load. The specific worry is ``type-v2``: the attribute appears in zero
        fixtures across document versions 8.3/10.4/18.1, so plain ``type`` is
        emitted; if 2026.2.0 requires ``type-v2`` every zone here is rejected.

        Child order is ``layout-options?, style, size, zones`` and is NOT
        negotiable - Tableau's loader enforces a DTD content model and rejects
        misordered children outright. ``repository-location``, ``simple-id`` and
        ``devicelayouts`` are published-only and deliberately omitted.

        A title needs TWO cooperating pieces: ``layout-options/title`` carries
        the text and a ``type="title"`` zone gives it canvas space. Emitting one
        without the other is a silent no-op (§6).
        """
        ids = _ZoneIds()
        node = ET.Element("dashboard", {"name": dash.name})

        # 1. title text. ElementTree escapes the text; no markup is ever built
        #    by string concatenation (T1).
        if dash.title:
            lo = ET.SubElement(node, "layout-options")
            title = ET.SubElement(lo, "title")
            ft = ET.SubElement(title, "formatted-text")
            ET.SubElement(ft, "run").text = dash.title

        # 2. present and empty in every fixture; emitted unconditionally.
        ET.SubElement(node, "style")

        # 3. <size> bounds are PIXELS. A fixed canvas sets min == max on both axes.
        if dash.sizing_mode == "fixed":
            ET.SubElement(
                node,
                "size",
                {
                    "maxheight": str(dash.height),
                    "maxwidth": str(dash.width),
                    "minheight": str(dash.height),
                    "minwidth": str(dash.width),
                    "sizing-mode": "fixed",
                },
            )
        else:
            ET.SubElement(node, "size", {"sizing-mode": "automatic"})

        # 4. <datasources>/<datasource-dependencies> are required only when a
        #    zone references a field (filter/legend/highlighter cards). This
        #    version places worksheets only, so both are correctly absent (§3).

        # 5. exactly one root zone at full grid extent.
        zones = ET.SubElement(node, "zones")
        root_zone = ET.SubElement(
            zones,
            "zone",
            {
                "h": str(ZONE_GRID),
                "id": ids.take(),
                "type": "layout-basic",
                "w": str(ZONE_GRID),
                "x": "0",
                "y": "0",
            },
        )

        flow_param = "vert" if dash.direction == "vertical" else "horz"
        has_title = bool(dash.title)

        if has_title and flow_param == "horz":
            # A horizontal strip of sheets cannot also hold the title card, so an
            # outer vertical flow stacks [title, horizontal strip].
            outer = self._flow_zone(root_zone, ids, "vert", 0, 0, ZONE_GRID, ZONE_GRID)
            self._title_zone(outer, ids, 0, 0, ZONE_GRID, TITLE_ZONE_GRID_HEIGHT)
            container = self._flow_zone(
                outer,
                ids,
                "horz",
                0,
                TITLE_ZONE_GRID_HEIGHT,
                ZONE_GRID,
                ZONE_GRID - TITLE_ZONE_GRID_HEIGHT,
            )
            content_x, content_y = 0, TITLE_ZONE_GRID_HEIGHT
            content_w, content_h = ZONE_GRID, ZONE_GRID - TITLE_ZONE_GRID_HEIGHT
        else:
            container = self._flow_zone(root_zone, ids, flow_param, 0, 0, ZONE_GRID, ZONE_GRID)
            content_x, content_y = 0, 0
            content_w, content_h = ZONE_GRID, ZONE_GRID
            if has_title:
                self._title_zone(container, ids, 0, 0, ZONE_GRID, TITLE_ZONE_GRID_HEIGHT)
                content_y = TITLE_ZONE_GRID_HEIGHT
                content_h = ZONE_GRID - TITLE_ZONE_GRID_HEIGHT

        # Worksheet zones tile the container exactly along its flow axis.
        count = len(dash.worksheets)
        if flow_param == "vert":
            spans = _tile(count, content_h, content_y)
            boxes = [(content_x, start, content_w, size) for start, size in spans]
        else:
            spans = _tile(count, content_w, content_x)
            boxes = [(start, content_y, size, content_h) for start, size in spans]

        for placed, (x, y, w, h) in zip(dash.worksheets, boxes, strict=True):
            # A worksheet zone is identified by having a 'name' and NO 'type'
            # attribute. The link is a bare name string - there is no id-based
            # reference in the format (§4.4).
            attrs = {"h": str(h), "id": ids.take(), "name": placed.worksheet}
            if not placed.show_title:
                attrs["show-title"] = "false"
            attrs.update({"w": str(w), "x": str(x), "y": str(y)})
            _zone_style(ET.SubElement(container, "zone", attrs), ZONE_MARGIN)

        # The root zone's own style must follow its nested zones.
        _zone_style(root_zone, ROOT_ZONE_MARGIN)
        return node

    @staticmethod
    def _flow_zone(
        parent: ET.Element, ids: _ZoneIds, param: str, x: int, y: int, w: int, h: int
    ) -> ET.Element:
        """A ``layout-flow`` container. ``param`` is 'horz' or 'vert' (§4.7)."""
        return ET.SubElement(
            parent,
            "zone",
            {
                "h": str(h),
                "id": ids.take(),
                "param": param,
                "type": "layout-flow",
                "w": str(w),
                "x": str(x),
                "y": str(y),
            },
        )

    @staticmethod
    def _title_zone(
        parent: ET.Element, ids: _ZoneIds, x: int, y: int, w: int, h: int
    ) -> ET.Element:
        """The card that gives ``layout-options/title`` space on the canvas (§6)."""
        zone = ET.SubElement(
            parent,
            "zone",
            {
                "h": str(h),
                "id": ids.take(),
                "type": "title",
                "w": str(w),
                "x": str(x),
                "y": str(y),
            },
        )
        _zone_style(zone, ZONE_MARGIN)
        return zone

    # -------------------------------------------------------------- assemble
    def build(self, *, data_dir_ref: str) -> ET.ElementTree:
        """Compile the full workbook.

        ``data_dir_ref`` is the **root** directory holding the data, written into
        the XML verbatim and resolved by Tableau relative to the workbook file.
        Each data source gets ``<data_dir_ref>/<ds_id>/`` beneath it. The caller
        owns the value because only the caller knows where the bytes went:
        ``"Data"`` for a ``.twbx`` (the layout ``packaging.twbx`` writes into the
        archive), a sidecar directory next to the file for a bare ``.twb``.

        It is never absolute. The docstring here used to promise "absolute for a
        bare .twb", which is not merely unimplemented but unimplementable: T6
        forbids machine-identifying paths in a world-readable artifact, and
        ``build_workbook`` refuses to continue when ``contains_machine_identifiers``
        finds one. Every path this compiler can legally emit is relative, so the
        pipeline must put the data where the XML says it is.
        """
        root = ET.Element(
            "workbook",
            {
                "original-version": DOC_VERSION,
                "source-build": SOURCE_BUILD,
                "source-platform": SOURCE_PLATFORM,
                "version": DOC_VERSION,
            },
        )
        prefs = ET.SubElement(root, "preferences")
        ET.SubElement(prefs, "preference", {"name": "ui.encoding.shelf.height", "value": "24"})
        ET.SubElement(prefs, "preference", {"name": "ui.shelf.height", "value": "26"})

        ds_parent = ET.SubElement(root, "datasources")
        for ds in self.spec.data_sources:
            ds_parent.append(self._build_datasource(ds.id, data_dir_ref))

        ws_parent = ET.SubElement(root, "worksheets")
        for ws in self.spec.worksheets:
            ws_parent.append(self._build_worksheet(ws))

        # <dashboards> sits between <worksheets> and <windows> in every fixture
        # across document versions 8.3/10.4/18.1, and carries no attributes (§2).
        if self.spec.dashboards:
            db_parent = ET.SubElement(root, "dashboards")
            for dash in self.spec.dashboards:
                db_parent.append(self._build_dashboard(dash))

        windows = ET.SubElement(root, "windows", {"source-height": "278"})
        # Exactly one window is maximized. When a dashboard exists it is the
        # entry point, so it takes the flag instead of the first worksheet.
        has_dashboards = bool(self.spec.dashboards)
        for i, ws in enumerate(self.spec.worksheets):
            win = ET.SubElement(
                windows,
                "window",
                {"class": "worksheet", "name": ws.name, "maximized": "true"}
                if i == 0 and not has_dashboards
                else {"class": "worksheet", "name": ws.name},
            )
            cards = ET.SubElement(win, "cards")
            left = ET.SubElement(cards, "edge", {"name": "left"})
            strip = ET.SubElement(left, "strip", {"size": "160"})
            for ctype in ("pages", "filters", "marks"):
                ET.SubElement(strip, "card", {"type": ctype})
            top = ET.SubElement(cards, "edge", {"name": "top"})
            for ctype, size in (("columns", "2147483647"), ("rows", "2147483647"), ("title", "31")):
                s = ET.SubElement(top, "strip", {"size": size})
                ET.SubElement(s, "card", {"type": ctype})
            if ws.filters:
                right = ET.SubElement(cards, "edge", {"name": "right"})
                rstrip = ET.SubElement(right, "strip", {"size": "160"})
                ds_name = self._ds_names[ws.data_source]
                fmap = self.spec.data_source(ws.data_source).field_map()
                for fname in ws.filters:
                    inst = _instance_name(fmap[fname], "None")
                    ET.SubElement(
                        rstrip,
                        "card",
                        {
                            "mode": "checkdropdown",
                            "param": _qualified(ds_name, inst),
                            "type": "filter",
                        },
                    )

            # How the viz fills its canvas. Stored as <viewpoint><zoom> AFTER
            # <cards> - not on the worksheet, which is why it is easy to miss.
            # Without it Tableau uses "Standard", which draws a small viz tucked
            # into the top-left corner instead of filling the view.
            zoom = ZOOM_TYPE.get(ws.fit or default_fit(ws.template))
            if zoom:
                vp = ET.SubElement(win, "viewpoint")
                ET.SubElement(vp, "zoom", {"type": zoom})

        # A dashboard window has <viewpoints> + <active> and, unlike a worksheet
        # window, NO <cards>: a dashboard has no shelves (§7).
        for i, dash in enumerate(self.spec.dashboards):
            win = ET.SubElement(
                windows,
                "window",
                {"class": "dashboard", "name": dash.name, "maximized": "true"}
                if i == 0
                else {"class": "dashboard", "name": dash.name},
            )
            viewpoints = ET.SubElement(win, "viewpoints")
            for ws_name in dash.worksheet_names():
                ET.SubElement(viewpoints, "viewpoint", {"name": ws_name})
            ET.SubElement(win, "active", {"id": "-1"})

        ET.indent(root, space="  ")
        return ET.ElementTree(root)

    def to_bytes(self, *, data_dir_ref: str) -> bytes:
        tree = self.build(data_dir_ref=data_dir_ref)
        import io

        buf = io.BytesIO()
        tree.write(buf, encoding="utf-8", xml_declaration=True)
        return buf.getvalue()


def _remote_type(datatype: str) -> str:
    """ODBC-style remote type codes Tableau writes into metadata-records."""
    return {
        "string": "129",
        "integer": "20",
        "real": "5",
        "boolean": "11",
        "date": "133",
        "datetime": "135",
    }.get(datatype, "129")


# NOTE: ``write_twb(spec, out_path, *, data_dir_ref)`` was deleted, not fixed.
# It had no callers anywhere in src/, tests/ or docs/, and its contract -
# "compile and write a bare .twb" - cannot be honoured by a function that only
# writes XML. A standalone .twb is usable only if the .hyper extract and the CSV
# it names exist next to it, so producing one means building extracts and staging
# data: the pipeline in compiler/build.py, not a one-line writer. Keeping it
# would have kept an exported way to produce exactly the unopenable artifact
# ``data_dir_ref`` was just fixed to prevent. Use ``build_workbook`` with
# ``output.package_twbx: false``.
