"""Build reproducible B84 baseline inspection reports using only the standard library."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ALLOWED_IDENTITIES = frozenset({"B84-reported", "B84-reproduced"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CURRENT_REPRODUCED_PARAMETERS = frozenset(
    {
        "smooth_alpha",
        "height_adjust",
        "root_origin_offset",
        "camera_follow",
        "ground_clearance",
    }
)
REQUIRED_DESCRIPTOR_FIELDS = frozenset(
    {
        "schema_version",
        "identity",
        "provenance",
        "input_assumptions",
        "robot",
        "model_paths",
        "artifacts",
        "coordinate_conventions",
        "expected",
        "parameters",
        "commands",
        "known_values",
        "unknown_fields",
        "critical_packages",
    }
)


class DescriptorError(ValueError):
    """Raised when a baseline descriptor cannot be trusted."""


def _as_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DescriptorError(f"{field} must be a JSON object")
    return value


def _resolve_repository_path(value: Any, repository_root: Path, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise DescriptorError(f"{field} must be a non-empty relative path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise DescriptorError(f"{field} must not contain path traversal")
    resolved = (repository_root / candidate).resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError as error:
        raise DescriptorError(f"{field} resolves outside the repository") from error
    return resolved


def _paths_overlap(first: Path, second: Path) -> bool:
    """Return whether either resolved path is the other path or its descendant."""
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def _resolve_descriptor_field(descriptor: dict[str, Any], field_path: str) -> Any:
    current: Any = descriptor
    for component in field_path.split("."):
        if not component or not isinstance(current, dict) or component not in current:
            raise DescriptorError(f"unknown_fields path does not exist: {field_path}")
        current = current[component]
    return current


def validate_descriptor(
    descriptor: dict[str, Any], repository_root: Path | None = None
) -> None:
    """Reject descriptor shapes and paths that do not form the B84 data contract."""
    if not isinstance(descriptor, dict):
        raise DescriptorError("descriptor must be a JSON object")
    if descriptor.get("identity") not in ALLOWED_IDENTITIES:
        raise DescriptorError(
            "identity must be one of: B84-reported, B84-reproduced"
        )

    missing = sorted(REQUIRED_DESCRIPTOR_FIELDS.difference(descriptor))
    if missing:
        raise DescriptorError(f"descriptor is missing required fields: {', '.join(missing)}")
    if descriptor["schema_version"] != 1:
        raise DescriptorError("schema_version must be 1")
    if descriptor["robot"] != "linglong2":
        raise DescriptorError("robot must be linglong2")

    expected = _as_mapping(descriptor["expected"], "expected")
    if expected.get("qpos_width") != 37:
        raise DescriptorError("expected.qpos_width must be 37")
    if expected.get("frame_count") is None or expected.get("fps") is None:
        raise DescriptorError("expected.frame_count and expected.fps are required")

    conventions = _as_mapping(
        descriptor["coordinate_conventions"], "coordinate_conventions"
    )
    required_conventions = {
        "root_position_slice": "qpos[0:3]",
        "source_quaternion_order": "wxyz",
        "csv_quaternion_order": "xyzw",
        "joint_count": 30,
    }
    for field, expected_value in required_conventions.items():
        if conventions.get(field) != expected_value:
            raise DescriptorError(
                f"coordinate_conventions.{field} must be {expected_value!r}"
            )
    joint_order = conventions.get("joint_order")
    if not isinstance(joint_order, list) or len(joint_order) != 30:
        raise DescriptorError("coordinate_conventions.joint_order must contain 30 joints")

    artifacts = descriptor["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise DescriptorError("artifacts must be a non-empty list")
    names: set[str] = set()
    for index, artifact in enumerate(artifacts):
        artifact = _as_mapping(artifact, f"artifacts[{index}]")
        name = artifact.get("name")
        if not isinstance(name, str) or not name:
            raise DescriptorError(f"artifacts[{index}].name must be a non-empty string")
        if name in names:
            raise DescriptorError(f"artifact names must be unique: {name}")
        names.add(name)
        if artifact.get("kind") not in {"qpos_csv", "retarget_metadata", "supplementary"}:
            raise DescriptorError(f"artifacts[{index}].kind is not supported")
        if not isinstance(artifact.get("path"), str) or not artifact["path"]:
            raise DescriptorError(
                f"artifacts[{index}].path must be a non-empty relative path"
            )

    if not isinstance(descriptor["unknown_fields"], list) or not all(
        isinstance(value, str) for value in descriptor["unknown_fields"]
    ):
        raise DescriptorError("unknown_fields must be a list of strings")
    for field_path in descriptor["unknown_fields"]:
        if _resolve_descriptor_field(descriptor, field_path) is not None:
            raise DescriptorError(f"unknown_fields path must have a null value: {field_path}")

    parameters = _as_mapping(descriptor["parameters"], "parameters")
    if descriptor["identity"] == "B84-reported":
        for parameter_name in CURRENT_REPRODUCED_PARAMETERS:
            if parameters.get(parameter_name) is not None:
                raise DescriptorError(
                    f"B84-reported parameters.{parameter_name} must be null"
                )
    if not isinstance(descriptor["critical_packages"], list) or not all(
        isinstance(value, str) and value for value in descriptor["critical_packages"]
    ):
        raise DescriptorError("critical_packages must be a list of non-empty strings")

    if repository_root is not None:
        root = repository_root.resolve()
        model_paths = _as_mapping(descriptor["model_paths"], "model_paths")
        for name, value in model_paths.items():
            if value is not None:
                _resolve_repository_path(value, root, f"model_paths.{name}")
        for index, artifact in enumerate(artifacts):
            _resolve_repository_path(artifact["path"], root, f"artifacts[{index}].path")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_qpos_csv(path: Path, expected: dict[str, Any], label: str) -> tuple[dict[str, Any], list[str]]:
    row_count = 0
    width: int | None = None
    finite = True
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            for row_number, row in enumerate(csv.reader(source, strict=True), start=1):
                if not row:
                    errors.append(f"{label} CSV row {row_number} is empty")
                    continue
                row_count += 1
                if width is None:
                    width = len(row)
                elif len(row) != width:
                    errors.append(
                        f"{label} CSV row {row_number} has {len(row)} columns; expected {width}"
                    )
                for column_number, value in enumerate(row, start=1):
                    try:
                        numeric_value = float(value)
                    except ValueError:
                        finite = False
                        errors.append(
                            f"{label} CSV row {row_number} column {column_number} is not numeric"
                        )
                        continue
                    if not math.isfinite(numeric_value):
                        finite = False
                        errors.append(
                            f"{label} CSV row {row_number} column {column_number} is not finite"
                        )
    except (OSError, csv.Error) as error:
        errors.append(f"could not read {label} CSV: {error}")

    if row_count == 0:
        errors.append(f"{label} CSV is empty")
    expected_width = expected["qpos_width"]
    expected_frames = expected["frame_count"]
    width_matches = width == expected_width
    frame_count_matches = row_count == expected_frames
    if width is not None and not width_matches:
        errors.append(f"{label} CSV width {width} does not match expected {expected_width}")
    if not frame_count_matches:
        errors.append(
            f"{label} CSV row count {row_count} does not match expected {expected_frames}"
        )
    return (
        {
            "row_count": row_count,
            "consistent_width": width,
            "finite_numeric_values": finite,
            "expected_frame_count_match": frame_count_matches,
            "expected_qpos_width_match": width_matches,
        },
        errors,
    )


def _inspect_metadata(
    path: Path, descriptor: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    conventions = descriptor["coordinate_conventions"]
    expected = descriptor["expected"]
    report: dict[str, Any] = {"exists": True, "actual": None, "checks": {}}
    errors: list[str] = []
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        report["read_error"] = str(error)
        return report, [f"could not parse retarget metadata: {error}"]
    if not isinstance(actual, dict):
        return report, ["retarget metadata must be a JSON object"]

    report["actual"] = actual
    root = actual.get("root") if isinstance(actual.get("root"), dict) else {}
    actual_joints = actual.get("joints") if isinstance(actual.get("joints"), list) else []
    try:
        actual_joint_order = [
            entry["jointName"]
            for entry in sorted(actual_joints, key=lambda entry: entry["csvIndex"])
        ]
    except (KeyError, TypeError):
        actual_joint_order = []
        errors.append("retarget metadata joints must provide csvIndex and jointName")

    checks = {
        "robot": (actual.get("robot"), descriptor["robot"]),
        "qposLength": (actual.get("qposLength"), expected["qpos_width"]),
        "csvColumns": (actual.get("csvColumns"), expected["qpos_width"]),
        "root_position_slice": (root.get("position"), conventions["root_position_slice"]),
        "source_quaternion_order": (
            root.get("quatSourceOrder"),
            conventions["source_quaternion_order"],
        ),
        "csv_quaternion_order": (
            root.get("csvQuatOrder"),
            conventions["csv_quaternion_order"],
        ),
        "joint_count": (len(actual_joint_order), conventions["joint_count"]),
        "joint_order": (actual_joint_order, conventions["joint_order"]),
    }
    for name, (actual_value, expected_value) in checks.items():
        matches = actual_value == expected_value
        report["checks"][name] = {
            "actual": actual_value,
            "expected": expected_value,
            "matches": matches,
        }
        if not matches:
            errors.append(
                f"metadata {name} mismatch: expected {expected_value!r}, got {actual_value!r}"
            )
    return report, errors


def _git_commit(repository_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _package_context(packages: list[str]) -> dict[str, dict[str, str]]:
    context: dict[str, dict[str, str]] = {}
    for package in packages:
        try:
            context[package] = {"status": "available", "version": importlib.metadata.version(package)}
        except importlib.metadata.PackageNotFoundError:
            context[package] = {"status": "unavailable"}
    return context


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    validation = report["validation"]
    lines = [
        f"# {report['deterministic']['descriptor']['identity']} Baseline Report",
        "",
        "This is proxy engineering evidence, not an official score or reconstructed official formula.",
        "",
        "## Contract",
        "",
        f"- Validation: {'PASS' if validation['passed'] else 'FAIL'}",
        f"- Robot: {report['deterministic']['descriptor']['robot']}",
        f"- Expected frames / qpos width: {report['deterministic']['contract']['expected']['frame_count']} / {report['deterministic']['contract']['expected']['qpos_width']}",
        "",
        "## Artifacts",
        "",
        "| Name | Exists | Bytes | SHA256 |",
        "| --- | --- | ---: | --- |",
    ]
    for artifact in report["artifacts"]:
        lines.append(
            f"| {artifact['name']} | {artifact['exists']} | {artifact['size_bytes']} | {artifact['sha256']} |"
        )
    lines.extend(["", "## Validation Details", ""])
    if validation["errors"]:
        lines.extend(f"- {error}" for error in validation["errors"])
    else:
        lines.append("- All inspected present artifacts satisfy the declared contract.")
    lines.extend(
        [
            "",
            "## Runtime Context",
            "",
            f"- Generated UTC: {report['runtime']['generated_at_utc']}",
            f"- Python: {report['runtime']['python_version']}",
            f"- Git commit: {report['runtime']['git_commit']}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_report(
    descriptor_path: str | Path,
    output_dir: str | Path,
    *,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect a descriptor without modifying its declared source artifacts."""
    root = Path(repository_root or REPOSITORY_ROOT).resolve()
    source_path = Path(descriptor_path).resolve()
    try:
        descriptor = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DescriptorError(f"could not load descriptor: {error}") from error
    validate_descriptor(descriptor, root)

    destination = Path(output_dir).resolve()
    identity = descriptor["identity"]
    json_path = destination / f"baseline-report-{identity}.json"
    markdown_path = destination / f"baseline-report-{identity}.md"
    artifact_paths = [
        _resolve_repository_path(artifact["path"], root, f"artifact {artifact['name']}")
        for artifact in descriptor["artifacts"]
    ]
    output_paths = (destination, json_path, markdown_path)
    if any(
        _paths_overlap(output_path, artifact_path)
        for output_path in output_paths
        for artifact_path in artifact_paths
    ):
        raise DescriptorError("output directory conflicts with a declared source artifact")

    errors: list[str] = []
    artifact_reports: list[dict[str, Any]] = []
    metadata_report: dict[str, Any] = {"exists": False, "actual": None, "checks": {}}
    for artifact, artifact_path in zip(descriptor["artifacts"], artifact_paths):
        exists = artifact_path.is_file()
        record: dict[str, Any] = {
            "name": artifact["name"],
            "kind": artifact["kind"],
            "declared_path": artifact["path"],
            "exists": exists,
            "size_bytes": artifact_path.stat().st_size if exists else None,
            "sha256": _hash_file(artifact_path) if exists else None,
        }
        if artifact["kind"] == "qpos_csv" and exists:
            csv_contract, csv_errors = _inspect_qpos_csv(
                artifact_path, descriptor["expected"], artifact["name"]
            )
            record["csv_contract"] = csv_contract
            errors.extend(csv_errors)
        elif artifact["kind"] == "qpos_csv":
            record["csv_contract"] = {
                "row_count": None,
                "consistent_width": None,
                "finite_numeric_values": None,
                "expected_frame_count_match": None,
                "expected_qpos_width_match": None,
            }
        if artifact["kind"] == "retarget_metadata":
            if exists:
                metadata_report, metadata_errors = _inspect_metadata(artifact_path, descriptor)
                errors.extend(metadata_errors)
            else:
                metadata_report = {"exists": False, "actual": None, "checks": {}}
        artifact_reports.append(record)

    deterministic = {
        "descriptor": descriptor,
        "contract": {
            "expected": descriptor["expected"],
            "coordinate_conventions": descriptor["coordinate_conventions"],
        },
    }
    report = {
        "deterministic": deterministic,
        "artifacts": artifact_reports,
        "metadata": metadata_report,
        "validation": {"passed": not errors, "errors": errors},
        "runtime": {
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "conda_default_env": os.environ.get("CONDA_DEFAULT_ENV"),
            "sys_executable": sys.executable,
            "python_version": sys.version,
            "git_commit": _git_commit(root),
            "critical_packages": _package_context(descriptor["critical_packages"]),
        },
    }
    destination.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_markdown(report, markdown_path)
    return {"report": report, "json_path": json_path, "markdown_path": markdown_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("descriptor", help="Path to a B84 baseline descriptor JSON file")
    parser.add_argument("output_dir", help="Directory for the JSON and Markdown reports")
    parser.add_argument(
        "--repository-root",
        default=REPOSITORY_ROOT,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    try:
        result = build_report(
            args.descriptor,
            args.output_dir,
            repository_root=args.repository_root,
        )
    except DescriptorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(result["json_path"])
    print(result["markdown_path"])
    return 0 if result["report"]["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
