"""MCP server exposing Tableau Public authoring, validation and publishing."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .capabilities import describe_capabilities, describe_templates
from .compiler.build import build_workbook as _build
from .desktop import tableau_app as app
from .models.spec import SPEC_VERSION, SpecError, parse_spec
from .packaging.twbx import inspect_twbx
from .publishing import publisher
from .security.paths import PathSecurityError, resolve_output_dir

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


_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["spec"],
    "properties": {
        "spec": {
            "type": "object",
            "description": (
                "Workbook authoring specification (spec_version 0.1). See "
                "schemas/workbook-spec-v0.1.json for the full contract."
            ),
        }
    },
}


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
                "spec's output.directory. Deterministic: identical specs produce "
                "identical output."
            ),
            inputSchema=_SPEC_SCHEMA,
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
                "required": ["workbook_window", "public_name", "confirm_publish"],
                "properties": {
                    "workbook_window": {
                        "type": "string",
                        "description": "Substring of the open Tableau window title to publish",
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
                    "is_validation_test": {
                        "type": "boolean",
                        "default": True,
                        "description": "Marks this as a labelled validation artifact.",
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
                "note": "dry run — no files were written",
            }
        )

    if name == "build_workbook":
        result = _build(args["spec"])
        return _ok({"build": result.to_dict()})

    if name == "inspect_local_workbook":
        p = Path(args["path"]).expanduser()
        if not p.is_absolute():
            return _err("path must be absolute")
        if not p.exists():
            return _err(f"file does not exist: {p}")
        return _ok({"inspection": inspect_twbx(p)})

    if name == "get_tableau_public_app_status":
        return _ok({"status": app.status().to_dict()})

    if name == "open_in_tableau_public":
        p = Path(args["path"]).expanduser()
        res = app.open_workbook(p, timeout=float(args.get("timeout_s", 90)))
        return _ok({"open": res})

    if name == "validate_in_tableau_public":
        p = Path(args["path"]).expanduser()
        shot_dir = resolve_output_dir(args.get("screenshot_dir") or str(p.parent / "screenshots"))
        res = app.open_workbook(p, timeout=120)
        payload: dict[str, Any] = {"open": res, "layers": {"layer3_open": res["opened"]}}
        if not res["opened"]:
            payload["layers"]["layer4_screenshot"] = False
            return _ok({"validation": payload})

        time.sleep(float(args.get("settle_s", 8)))
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

        # Overwrite protection: refuse to clobber an existing published workbook.
        if profile:
            try:
                from .publishing.existing import assert_safe_to_publish

                safe, why = assert_safe_to_publish(str(profile), public_name, overwrite=overwrite)
                if not safe:
                    return _err(why)
            except ImportError:
                pass

        res = publisher.publish(
            workbook_window=str(args["workbook_window"]),
            public_name=public_name,
            screenshot_dir=shot_dir,
            profile=str(profile) if profile else None,
            set_title=bool(args.get("set_title", True)),
        )
        return _ok({"publish": res.to_dict()})

    if name == "verify_published_workbook":
        url = str(args["url"])
        if not url.startswith("https://public.tableau.com/"):
            return _err("url must be a https://public.tableau.com/ address")
        okd, status = publisher.verify_url(url)
        return _ok({"verified": okd, "http_status": status, "url": url})

    return _err(f"unknown tool: {name}")


async def _serve() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    import asyncio

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
