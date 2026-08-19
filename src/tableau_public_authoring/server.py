"""MCP server exposing Tableau Public authoring, validation and publishing."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .capabilities import describe_capabilities, describe_templates
from .compiler.build import build_workbook as _build
from .desktop import tableau_app as app
from .models.spec import SPEC_VERSION, SpecError, parse_spec, spec_json_schema
from .packaging.twbx import inspect_twbx
from .publishing import publisher
from .security.paths import PathSecurityError, resolve_input_file, resolve_output_dir

# A .twbx embeds every Hyper extract, so it is legitimately far larger than the
# CSV ceiling resolve_input_file defaults to.
MAX_WORKBOOK_BYTES = 512 * 1024 * 1024

SERVER_NAME = "tableau-public-authoring"
SERVER_VERSION = "0.1.0"

server: Server = Server(SERVER_NAME)


def _ok(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"ok": True, **payload}, indent=2))]


def _err(message: str, **extra: Any) -> list[TextContent]:
    return [
        TextContent(
            type="text", text=json.dumps({"ok": False, "error": message, **extra}, indent=2)
        )
    ]


def _spec_argument_schema() -> dict[str, Any]:
    """The publish-time contract for a ``spec`` argument.

    The real schema is generated from the spec model by
    ``models.spec.spec_json_schema`` and pinned to it by
    ``tests/unit/test_schema_contract.py``, so what a client is told and what
    ``parse_spec`` enforces cannot drift apart.

    This used to advertise ``{"type": "object"}`` plus prose pointing at
    ``schemas/workbook-spec-v0.1.json`` -- a file that is not packaged in the
    wheel, so an installed deployment sent callers to a path that did not exist.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["spec"],
        "properties": {"spec": spec_json_schema()},
    }


_SPEC_SCHEMA: dict[str, Any] = _spec_argument_schema()


def _build_argument_schema() -> dict[str, Any]:
    """``build_workbook``'s arguments: a spec, plus an explicit overwrite flag.

    The compiler refuses to overwrite a file it cannot prove it wrote itself, so
    without a way to say "yes, replace it" a caller who has a same-named foreign
    file in the output directory has no recovery except renaming it by hand.
    Rebuilding the *same* spec never needs this -- prior output is recognised by
    provenance and replaced silently, because it is regenerable.

    Deliberately not offered on ``validate_workbook_spec``: a dry run writes
    nothing, so it has nothing to overwrite.
    """
    schema = _spec_argument_schema()
    schema["properties"]["overwrite"] = {
        "type": "boolean",
        "default": False,
        "description": (
            "Replace files in the output directory that this server did not "
            "generate. Rebuilding the same workbook does not require it."
        ),
    }
    return schema


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_authoring_capabilities",
            description=(
                "Report what this server can and cannot author, the detected Tableau "
                "Public installation, and the macOS permission state. Read-only."
            ),
            inputSchema={"type": "object", "additionalProperties": False, "properties": {}},
        ),
        Tool(
            name="list_workbook_templates",
            description="List supported worksheet templates and their required shelves. Read-only.",
            inputSchema={"type": "object", "additionalProperties": False, "properties": {}},
        ),
        Tool(
            name="validate_workbook_spec",
            description=(
                "Validate an authoring specification without writing any files "
                "(dry run). Returns actionable errors. Read-only."
            ),
            inputSchema=_SPEC_SCHEMA,
        ),
        Tool(
            name="build_workbook",
            description=(
                "PRIMARY TOOL. Compile a specification into a .twb and packaged .twbx "
                "with Hyper extracts (required by Tableau Public). Writes files to the "
                "spec's output.directory. The .twb is byte-deterministic for an "
                "identical spec; the .twbx digest is not, because the embedded Hyper "
                "extract carries non-deterministic state."
            ),
            inputSchema=_build_argument_schema(),
        ),
        Tool(
            name="inspect_local_workbook",
            description="Safely inspect a local .twbx archive's contents. Read-only.",
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {"path": {"type": "string", "description": "Absolute .twbx path"}},
            },
        ),
        Tool(
            name="get_tableau_public_app_status",
            description=(
                "Report Tableau Public installation, version, running state, open "
                "windows and Accessibility permission. Read-only."
            ),
            inputSchema={"type": "object", "additionalProperties": False, "properties": {}},
        ),
        Tool(
            name="open_in_tableau_public",
            description=(
                "Open a generated workbook in Tableau Public and wait for its window. "
                "Returns the load error verbatim if Tableau rejects the file."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Absolute .twb or .twbx path"},
                    "timeout_s": {"type": "number", "default": 90, "minimum": 10, "maximum": 600},
                },
            },
        ),
        Tool(
            name="validate_in_tableau_public",
            description=(
                "Layer 3+4 validation: open the workbook in Tableau Public, detect "
                "error dialogs, and capture a screenshot proving rendered content."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "screenshot_dir": {"type": "string"},
                    "settle_s": {"type": "number", "default": 8, "minimum": 0, "maximum": 60},
                },
            },
        ),
        Tool(
            name="publish_to_tableau_public",
            description=(
                "DESTRUCTIVE / PUBLIC. Publish an open workbook to the user's Tableau "
                "Public account through the visible Server > Tableau Public > Save to "
                "Tableau Public workflow. Publication is irreversible and world-visible. "
                "Requires confirm_publish=true. Never reads credentials; pauses for "
                "manual sign-in if required."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["workbook_window", "public_name", "confirm_publish", "profile"],
                "properties": {
                    "workbook_window": {
                        "type": "string",
                        "description": (
                            "The open workbook's exact name (its window title without the "
                            "'Tableau Public - ' prefix). Matched exactly, not as a substring, "
                            "because publishing is irreversible: a substring match would let "
                            "'Q3_Sales' publish 'Q3_Sales_Draft'."
                        ),
                    },
                    "public_name": {
                        "type": "string",
                        "description": "Name for the published workbook (must be unique)",
                    },
                    "confirm_publish": {
                        "type": "boolean",
                        "description": "Must be true. Guards against accidental publication.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "Allow overwriting an existing workbook of the same name.",
                    },
                    "workbook_path": {
                        "type": "string",
                        "description": (
                            "Absolute path to the .twbx being published. Optional but "
                            "recommended: it lets a minimized workbook be raised reliably "
                            "with `open -a` instead of a coordinate click."
                        ),
                    },
                    "profile": {
                        "type": "string",
                        "description": (
                            "Your Tableau Public profile name. Required to resolve and "
                            "verify the resulting public URL after publication."
                        ),
                    },
                    "set_title": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "Type public_name into the dialog's Workbook Title field. "
                            "If false, Tableau's pre-filled title (from the file name) is kept."
                        ),
                    },
                    "screenshot_dir": {"type": "string"},
                    "dry_run": {
                        "type": "boolean",
                        "default": False,
                        "description": "Report what would happen without publishing.",
                    },
                },
            },
        ),
        Tool(
            name="verify_published_workbook",
            description=(
                "Layer 5 validation: load a public Tableau URL and confirm it responds. Read-only."
            ),
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["url"],
                "properties": {"url": {"type": "string"}},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    args = arguments or {}
    try:
        return await _dispatch(name, args)
    except SpecError as exc:
        return _err(f"specification error: {exc}")
    except PathSecurityError as exc:
        return _err(f"path rejected: {exc}")
    except app.DesktopError as exc:
        return _err(f"desktop automation error: {exc}")
    except Exception as exc:  # noqa: BLE001 - the server must never crash on a tool error
        return _err(f"{type(exc).__name__}: {exc}")


async def _dispatch(name: str, args: dict[str, Any]) -> list[TextContent]:
    if name == "get_authoring_capabilities":
        return _ok(
            {
                "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "spec_version": SPEC_VERSION,
                **describe_capabilities(),
                "tableau_public": app.status().to_dict(),
            }
        )

    if name == "list_workbook_templates":
        return _ok({"templates": describe_templates()})

    if name == "validate_workbook_spec":
        spec = parse_spec(args["spec"])
        return _ok(
            {
                "valid": True,
                "workbook_name": spec.name,
                "data_sources": [
                    {"id": d.id, "csv": str(d.path), "fields": len(d.fields)}
                    for d in spec.data_sources
                ],
                "worksheets": [{"name": w.name, "template": w.template} for w in spec.worksheets],
                "output_directory": str(spec.output_dir),
                "note": "dry run - no files were written",
            }
        )

    if name == "build_workbook":
        # Spawns a Hyper process per data source; seconds, not milliseconds.
        result = await asyncio.to_thread(
            _build, args["spec"], overwrite=bool(args.get("overwrite", False))
        )
        return _ok({"build": result.to_dict()})

    if name == "inspect_local_workbook":
        # resolve_input_file enforces absoluteness, is_file(), the suffix and the
        # size cap. The hand-rolled check it replaces had none of those: a path
        # naming a FIFO passed, and zipfile.is_zipfile then blocked forever in
        # open(), wedging this single-threaded server permanently.
        p = resolve_input_file(
            args["path"], suffixes=(".twbx",), max_bytes=MAX_WORKBOOK_BYTES
        )
        return _ok({"inspection": inspect_twbx(p)})

    if name == "get_tableau_public_app_status":
        # The preflight is included because every environmental prerequisite of
        # this server fails SILENTLY: no Quartz means Tableau appears to have no
        # windows, no Screen Recording means blank screenshots, no Accessibility
        # means keystrokes that go nowhere. Without this, a caller sees a symptom
        # ("no document window matching X") three layers from the cause and has
        # no way to reach the diagnosis from inside the conversation.
        from .doctor import run as run_preflight

        report = run_preflight()
        return _ok(
            {
                "status": app.status().to_dict(),
                "preflight": {
                    "ready": not report.failed,
                    "checks": [
                        {"name": c.name, "state": c.state, "detail": c.detail, "fix": c.fix}
                        for c in report.checks
                    ],
                    "blocking": [c.name for c in report.failed],
                },
            }
        )

    if name == "open_in_tableau_public":
        # This hands a caller-supplied path straight to `open -a Tableau`. It
        # previously validated nothing at all, not even that the path was absolute.
        p = resolve_input_file(
            args["path"], suffixes=(".twb", ".twbx"), max_bytes=MAX_WORKBOOK_BYTES
        )
        res = await asyncio.to_thread(
            app.open_workbook, p, timeout=float(args.get("timeout_s", 90))
        )
        return _ok({"open": res})

    if name == "validate_in_tableau_public":
        p = resolve_input_file(
            args["path"], suffixes=(".twb", ".twbx"), max_bytes=MAX_WORKBOOK_BYTES
        )
        shot_dir = resolve_output_dir(args.get("screenshot_dir") or str(p.parent / "screenshots"))
        # open_workbook polls with time.sleep and shells out to `open`/osascript.
        # Run off the event loop: for up to two minutes the stdio server could not
        # read the next request, answer a ping, or honour a cancellation.
        res = await asyncio.to_thread(app.open_workbook, p, timeout=120)
        payload: dict[str, Any] = {"open": res, "layers": {"layer3_open": res["opened"]}}
        if not res["opened"]:
            payload["layers"]["layer4_screenshot"] = False
            return _ok({"validation": payload})

        await asyncio.sleep(float(args.get("settle_s", 8)))
        win = app.find_window(p.stem) or {"id": res.get("window_id")}
        shot = shot_dir / f"validate-{p.stem}.png"
        try:
            app.screenshot_window(int(win["id"]), shot)
            payload["screenshot"] = str(shot)
            payload["layers"]["layer4_screenshot"] = True
        except (app.DesktopError, TypeError, ValueError) as exc:
            payload["layers"]["layer4_screenshot"] = False
            payload["screenshot_error"] = str(exc)
        err = app.read_error_dialog(dismiss=True)
        payload["error_dialog"] = err
        payload["layers"]["no_error_dialog"] = err is None
        return _ok({"validation": payload})

    if name == "publish_to_tableau_public":
        if not args.get("confirm_publish"):
            return _err(
                "refusing to publish: confirm_publish must be true. Publication to "
                "Tableau Public is irreversible and world-visible."
            )
        public_name = str(args["public_name"]).strip()
        if not public_name:
            return _err("public_name must be a non-empty string")
        shot_dir = resolve_output_dir(
            args.get("screenshot_dir")
            or str(Path.home() / "dev/mcp-tableau-public-authoring/output/screenshots")
        )
        if args.get("dry_run"):
            return _ok(
                {
                    "dry_run": True,
                    "would_publish": {
                        "workbook_window": args["workbook_window"],
                        "public_name": public_name,
                        "overwrite": bool(args.get("overwrite", False)),
                        "is_validation_test": bool(args.get("is_validation_test", True)),
                        "expected_visibility": "public (world-readable)",
                        "menu_path": "Server > Tableau Public > Save to Tableau Public",
                    },
                    "file_menu_publish_items": [
                        i for i in publisher.file_menu_items() if "Tableau Public" in i
                    ],
                    "sign_in_required": publisher.detect_sign_in_required(),
                    "frontmost_document": publisher.frontmost_window_title(),
                }
            )
        overwrite = bool(args.get("overwrite", False))
        profile = args.get("profile")

        # Overwrite protection. This is the only thing standing between a publish
        # and silently replacing a workbook the user already has online, and
        # publication is irreversible. It used to be gated on `if profile:` while
        # `profile` was optional, so omitting one argument skipped the check
        # entirely -- the opposite of the "fails CLOSED" guarantee in
        # publishing/existing.py. It is now required.
        if not profile:
            return _err(
                "refusing to publish: 'profile' is required. Without it the server cannot "
                "check whether a workbook of this name is already published, and publishing "
                "would silently replace it. Pass your Tableau Public profile name."
            )
        try:
            from .publishing.existing import assert_safe_to_publish
        except ImportError as exc:
            # Never downgrade a missing guard to a warning.
            return _err(
                f"refusing to publish: the overwrite-protection module could not be "
                f"imported ({exc}), so a name collision cannot be ruled out."
            )
        safe, why = assert_safe_to_publish(str(profile), public_name, overwrite=overwrite)
        if not safe:
            return _err(why)

        # publisher.publish drives a GUI for up to several minutes.
        wb_path = args.get("workbook_path")
        res = await asyncio.to_thread(
            publisher.publish,
            workbook_window=str(args["workbook_window"]),
            public_name=public_name,
            screenshot_dir=shot_dir,
            # Passing the file lets a minimized workbook be raised with `open -a`,
            # which window_control documents as the reliable route. This was never
            # threaded through, so only the brittle click fallback was reachable.
            workbook_path=resolve_input_file(wb_path, suffixes=(".twb", ".twbx"))
            if wb_path
            else None,
            profile=str(profile) if profile else None,
            set_title=bool(args.get("set_title", True)),
        )
        return _ok({"publish": res.to_dict()})

    if name == "verify_published_workbook":
        url = str(args["url"])
        if not url.startswith("https://public.tableau.com/"):
            return _err("url must be a https://public.tableau.com/ address")
        okd, status = await asyncio.to_thread(publisher.verify_url, url)
        return _ok({"verified": okd, "http_status": status, "url": url})

    return _err(f"unknown tool: {name}")


async def _serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Entry point. No arguments runs the stdio server, which is how an MCP
    client invokes it; that behaviour is unchanged and must stay the default.

    ``doctor`` exists because every environmental prerequisite of this server
    fails silently at runtime, and diagnosing that from inside an MCP
    conversation means reading a symptom three layers from the cause.
    """
    import asyncio

    argv = sys.argv[1:]
    if argv and argv[0] in ("doctor", "--doctor", "check"):
        from .doctor import main as doctor_main

        raise SystemExit(doctor_main(argv[1:]))
    if argv and argv[0] in ("-h", "--help"):
        print(
            "tableau-public-authoring\n\n"
            "  (no arguments)   run the MCP stdio server (how an MCP client starts it)\n"
            "  doctor           check this machine can actually run it, and say what to fix\n"
            "  --version        print the server version\n"
        )
        raise SystemExit(0)
    if argv and argv[0] in ("--version", "-V"):
        print(f"{SERVER_NAME} {SERVER_VERSION}")
        raise SystemExit(0)

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
