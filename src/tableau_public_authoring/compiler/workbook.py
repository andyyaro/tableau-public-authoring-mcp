"""Tableau ``.twb`` XML compiler.

All XML is produced with :mod:`xml.etree.ElementTree` nodes. No markup is ever
built by string concatenation or substitution, which is what makes the compiler
immune to XML injection through user-supplied names and formulas (T1).

Node structures were derived from a real workbook produced by the installed
Tableau Public build (see docs/fixtures/EV_WORKBOOK_ANALYSIS.md). Version
metadata is pinned to that build.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..models.spec import EncodingRef, Worksheet, WorkbookSpec
from .fields import Field
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
}

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


class CompileError(RuntimeError):
    """Raised when a specification cannot be compiled into valid workbook XML."""


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
    return f"[{prefix}:{base}:{suffix}]"


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
    def _build_datasource(self, ds_id: str, _unused: str = "") -> ET.Element:
        ds = self.spec.data_source(ds_id)
        # Each data source owns its own Data/<id>/ directory inside the package.
        from ..packaging.twbx import data_dir_for

        data_dir_ref = data_dir_for(ds_id)
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
                "directory": data_dir_ref,
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
            attrs = {
                "datatype": f.datatype,
                "name": f.reference_name,
                "role": f.role,
                "type": f.type,
            }
            if f.is_calculated:
                attrs["caption"] = f.name
            col = ET.SubElement(node, "column", attrs)
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
                "dbname": f"{data_dir_ref}/{ds.hyper_name}",
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
                sub = ET.SubElement(
                    ft, "run", {"fontcolor": "#898989", "fontsize": "10"}
                )
                sub.text = ws.subtitle

        table = ET.SubElement(node, "table")
        view = ET.SubElement(table, "view")
        dss = ET.SubElement(view, "datasources")
        ET.SubElement(dss, "datasource", {"caption": ds.id, "name": ds_name})

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

        row_refs = [use(r) for r in ws.rows]
        col_refs = [use(c) for c in ws.columns]
        color_ref = use(ws.color)
        size_ref = use(ws.size)
        label_ref = use(ws.label)

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
        filter_refs = [use(EncodingRef(field=f, aggregation="None")) for f in ws.filters]

        # <column> declarations for every distinct field touched by this sheet
        declared: set[str] = set()
        for fld, _agg in used:
            if fld.reference_name in declared:
                continue
            declared.add(fld.reference_name)
            attrs = {
                "datatype": fld.datatype,
                "name": fld.reference_name,
                "role": fld.role,
                "type": fld.type,
            }
            if fld.is_calculated:
                attrs["caption"] = fld.name
            c = ET.SubElement(deps, "column", attrs)
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
            grp = ET.SubElement(
                filt, "groupfilter", {"function": "level-members", "level": inst}
            )
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
        for t in tooltip_refs:
            if t:
                ET.SubElement(enc, "tooltip", {"column": t})

        # A text table needs its measure on the Text encoding to render anything.
        if ws.template == "text_table" and not label_ref and col_refs:
            ET.SubElement(enc, "text", {"column": col_refs[0]})

        # <rows>/<cols> follow <panes> in the loader's content model.
        ET.SubElement(table, "rows").text = " / ".join(r for r in row_refs if r)
        ET.SubElement(table, "cols").text = " / ".join(c for c in col_refs if c)

        return node

    # -------------------------------------------------------------- assemble
    def build(self, *, data_dir_ref: str) -> ET.ElementTree:
        """Compile the full workbook. ``data_dir_ref`` is the CSV directory the
        generated XML should point at (relative for ``.twbx``, absolute for
        a bare ``.twb``)."""
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

        windows = ET.SubElement(root, "windows", {"source-height": "278"})
        for i, ws in enumerate(self.spec.worksheets):
            win = ET.SubElement(
                windows,
                "window",
                {"class": "worksheet", "name": ws.name, "maximized": "true"} if i == 0
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


def write_twb(spec: WorkbookSpec, out_path: Path, *, data_dir_ref: str) -> Path:
    """Compile and write a bare ``.twb``."""
    compiler = WorkbookCompiler(spec)
    out_path.write_bytes(compiler.to_bytes(data_dir_ref=data_dir_ref))
    return out_path
