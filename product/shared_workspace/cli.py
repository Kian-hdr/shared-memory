"""Versioned JSON boundary for the Shared Workspace CLI preview."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import PRODUCT_VERSION
from .bundle import open_bundle
from .errors import ProductError
from . import project
from . import workflow
from . import maintenance
from . import delivery_workflow
from . import knowledge_workflow
from . import coordination_workflow

COMMANDS = ("version", "guide", "capabilities", "create", "join", "doctor", "status", "work", "teammate-prompt")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ProductError(2, "usage_error", message)


def parser() -> argparse.ArgumentParser:
    result = Parser(prog="shared-workspace", description="Selected-folder collaboration CLI preview with explicit revision delivery.")
    result.add_argument("--bundle", help="Explicit reviewed built directory or package for source-mode execution")
    commands = result.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands.add_parser("version", help="Show exact package identity and build provenance")
    commands.add_parser("guide", help="Read the operating guide and optional server dependency pins bundled with this exact version")
    commands.add_parser("capabilities", help="Show implemented commands and unverified boundaries")
    create = commands.add_parser("create", help="Initialize only an existing selected project directory")
    create.add_argument("project")
    for name in ("person", "actor", "agent", "purpose"):
        create.add_argument("--" + name, required=True)
    create.add_argument("--mode", required=True, choices=project.MODES)
    join = commands.add_parser("join", help="Register this actor in a matching existing project")
    join.add_argument("project")
    for name in ("person", "actor", "agent", "expected-project-id", "expected-bundle-id"):
        join.add_argument("--" + name, required=True)
    for name in ("doctor", "status"):
        command = commands.add_parser(name)
        command.add_argument("project")
    work = commands.add_parser("work", help="Invoke trusted tracker ownership and evidence commands")
    work.add_argument("project")
    work.add_argument("tracker_args", nargs=argparse.REMAINDER)
    prompt = commands.add_parser("teammate-prompt", help="Produce joining instructions without sending them")
    prompt.add_argument("project")
    prompt.add_argument("--package-locator")
    prompt.add_argument("--access-locator")
    workflow.add_commands(commands)
    maintenance.add_commands(commands)
    delivery_workflow.add_commands(commands)
    knowledge_workflow.add_commands(commands)
    coordination_workflow.add_commands(commands)
    return result


def capabilities() -> dict:
    return {
        "commands": list(COMMANDS) + list(workflow.TEAM_COMMANDS) + list(maintenance.COMMANDS) + list(delivery_workflow.COMMANDS) + list(knowledge_workflow.COMMANDS) + list(coordination_workflow.COMMANDS),
        "implemented": {"selected_folder_setup": True, "portable_project_identity": True,
                        "trusted_bundle_execution": True, "json_output": True,
                        "advisory_claims_handoffs_and_evidence": True,
                        "atomic_coordinator_acceptance": True, "authenticated_membership": True,
                        "preserved_offline_drafts": True, "recoverable_materialization": True,
                        "reviewed_package_installation": True, "local_receipt_verification": True},
        "coordination_extension": {"opt_in_schema": 2, "default_schema": 1,
                                   "commands": list(coordination_workflow.COMMANDS),
                                   "explicit_session_credentials": True, "automatic_renewal": False,
                                   "live_vault_migration": False, "acceptance": "bounded_local_validation"},
        "knowledge_graph": {"commands": list(knowledge_workflow.COMMANDS), "read_only": True,
                            "sources": ["local_selected_folder", "accepted_coordinator_snapshot"],
                            "parent_vault_reads": False, "policy_authority": False,
                            "native_rename_command": False},
        "explicit_delivery": {"commands": list(delivery_workflow.COMMANDS),
                              "routes": ["local_fixture", "google_drive_rclone"],
                              "initial_join": "coordinator_attach_required",
                              "google_drive_live_acceptance": "not_run",
                              "automatic_sharing_or_login": False},
        "unsupported": {"verified_hosted_deployment": True, "provider_sync_automation": True, "provider_access_configuration": True,
                        "editor_write_exclusion": True, "multi_file_filesystem_atomicity": True, "federated_login": True,
                        "automatic_app_setup": True, "automatic_history_repair": True},
        "acceptance_gates": {"TEAM-01": "bounded_local_coverage_only", "TEAM-02": "bounded_local_coverage_only",
                             "TEAM-04": "bounded_local_coverage_only",
                             **{f"TEAM-{number:02d}": "local_engine_contract_coverage_only" for number in (3, 5, 6, 7, 8, 9)},
                             "TEAM-10": "live_provider_not_run", "TEAM-11": "mixed_os_not_run"},
        "release_status": "preview", "stable_v1": False,
        "python": {"minimum": "3.11", "rehearsal_baseline": "3.13"},
        "mixed_os_acceptance": "not_run", "hosted_remote_readiness": "unverified",
    }


def command_hint(arguments: list[str]) -> str | None:
    skip = False
    for value in arguments:
        if skip:
            skip = False
            continue
        if value == "--bundle":
            skip = True
            continue
        if not value.startswith("-"):
            return value
    return None


def emit(command, *, ok, code, data=None, warnings=None, message=None):
    result = {"schema_version": 1, "product_version": PRODUCT_VERSION, "command": command,
              "ok": ok, "code": code, "data": data or {}, "warnings": warnings or []}
    if message is not None:
        result["message"] = message
    # ASCII-safe JSON works on legacy console/pipe encodings without changing
    # decoded Unicode values or requiring the caller to force UTF-8 mode.
    print(json.dumps(result, ensure_ascii=True))


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = command_hint(arguments)
    try:
        if sys.version_info < (3, 11):
            raise ProductError(2, "unsupported_runtime", "Python 3.11 or newer is required; Python 3.13 is the rehearsal baseline.")
        args = parser().parse_args(arguments)
        command = args.command
        for name in ("person", "actor", "agent", "purpose"):
            if hasattr(args, name) and not getattr(args, name).strip():
                raise ProductError(2, "usage_error", f"--{name} cannot be empty.")
        with open_bundle(args.bundle) as bundle:
            if command in coordination_workflow.COMMANDS:
                data = coordination_workflow.dispatch(bundle, args)
            elif command in knowledge_workflow.COMMANDS:
                data = knowledge_workflow.dispatch(bundle, args)
            elif command in delivery_workflow.COMMANDS:
                data = delivery_workflow.dispatch(bundle, args)
            elif command in maintenance.COMMANDS:
                data = maintenance.dispatch(bundle, args)
            elif command in workflow.TEAM_COMMANDS:
                data = workflow.dispatch(bundle, args)
            elif command == "version":
                data = dict(bundle.build)
            elif command == "guide":
                data = {"guide": (bundle.root / "PRODUCT-GUIDE.md").read_text(encoding="utf-8"),
                        "knowledge_graph_guide": (bundle.root / "KNOWLEDGE-GRAPH.md").read_text(encoding="utf-8"),
                        "server_dependencies": (bundle.root / "requirements-server.txt").read_text(encoding="utf-8")}
            elif command == "capabilities":
                data = capabilities()
                data["bundle_id"] = bundle.build["bundle_id"]
            elif command == "doctor":
                data = project.diagnostics(bundle, project.project_root(args.project))
            else:
                operation = {"create": project.create, "join": project.join, "status": project.status,
                             "work": project.work, "teammate-prompt": project.teammate_prompt}[command]
                data = operation(bundle, args)
            warnings = []
            metadata = data.get("metadata", {})
            if metadata.get("mode") in {"shared-folder", "git", "hybrid"}:
                warnings.append(project.SHARED_WARNING)
            emit(command, ok=True, code="ok", data=data, warnings=warnings)
            return 0
    except ProductError as exc:
        emit(command, ok=False, code=exc.code, data=exc.data, warnings=exc.warnings, message=str(exc))
        return exc.exit_code
    except SystemExit as exc:
        # argparse help is the only intentionally non-JSON response.
        return int(exc.code or 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        emit(command, ok=False, code="environment_error", message=f"Required local IO or trusted toolkit process failed: {exc}")
        return 5
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        emit(command, ok=False, code="project_invalid", message="Package or project data is malformed; no automatic repair was attempted.")
        return 3
    except Exception as exc:
        # Untrusted notes can violate the old flat-record parser's assumptions.
        # Do not expose a traceback or let a target-provided exception escape JSON.
        emit(command, ok=False, code="operation_rejected", message=f"Operation could not complete safely ({type(exc).__name__}); inspect the existing project before retrying.")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
