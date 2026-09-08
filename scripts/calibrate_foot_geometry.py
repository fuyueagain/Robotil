"""Calibrate the LingLong2.0 ankle-frame sole geometry from checked-in MJCF."""

import argparse
import ast
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as element_tree
from pathlib import Path


ANCHORS = {"left": "left_ankle_roll_link", "right": "right_ankle_roll_link"}
SYMMETRY_TOLERANCE = 1e-6


class CalibrationError(ValueError):
    """An invalid or unsafe calibration input."""


def _resolved(path):
    return Path(path).resolve()


def _inside(path, root):
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def _repository_path(path, repository_root, label):
    resolved = _resolved(path)
    if not _inside(resolved, repository_root):
        raise CalibrationError(f"{label} escapes repository root")
    return resolved


def _parse_xml(path):
    try:
        return element_tree.parse(path).getroot()
    except (OSError, element_tree.ParseError) as error:
        raise CalibrationError(f"could not parse MJCF {path}: {error}") from error


def resolve_mjcf_includes(scene_path, repository_root):
    """Return scene and nested includes in deterministic depth-first source order."""
    root = _resolved(repository_root)
    scene = _repository_path(scene_path, root, "scene path")
    resolved = []
    visiting = set()
    visited = set()

    def visit(path):
        path = _repository_path(path, root, "MJCF include")
        if path in visiting:
            raise CalibrationError(f"MJCF include cycle at {path.relative_to(root).as_posix()}")
        if path in visited:
            return
        document = _parse_xml(path)
        visiting.add(path)
        resolved.append(path)
        for include in document.iter("include"):
            include_name = include.get("file")
            if not include_name:
                raise CalibrationError(f"include without file in {path.relative_to(root).as_posix()}")
            visit(path.parent / include_name)
        visiting.remove(path)
        visited.add(path)

    visit(scene)
    return resolved


def _vector(value, size, label, default=None):
    if value is None:
        if default is None:
            raise CalibrationError(f"{label} is required")
        return tuple(default)
    try:
        values = tuple(float(part) for part in value.split())
    except ValueError as error:
        raise CalibrationError(f"{label} must be numeric") from error
    if len(values) != size or not all(math.isfinite(part) for part in values):
        raise CalibrationError(f"{label} must contain {size} finite values")
    return values


def _normalized_quaternion(quaternion):
    norm = math.sqrt(sum(component * component for component in quaternion))
    if not math.isfinite(norm) or norm == 0.0:
        raise CalibrationError("geom quaternion must have non-zero finite length")
    return tuple(component / norm for component in quaternion)


def cylinder_axis(quaternion):
    """Rotate the cylinder's local +Z axis with an MJCF wxyz quaternion."""
    w, x, y, z = _normalized_quaternion(tuple(quaternion))
    return (
        2.0 * (x * z + w * y),
        2.0 * (y * z - w * x),
        1.0 - 2.0 * (x * x + y * y),
    )


def cylinder_support_point(centre, quaternion, radius, half_length):
    """Return one exact body-local point at a cylinder's lowest Z support."""
    if not all(math.isfinite(value) for value in (*centre, radius, half_length)):
        raise CalibrationError("cylinder values must be finite")
    if radius <= 0.0 or half_length <= 0.0:
        raise CalibrationError("cylinder radius and half-length must be positive")

    axis = cylinder_axis(quaternion)
    axis_z = axis[2]
    axial_direction = 1.0 if axis_z >= 0.0 else -1.0
    axial = tuple(-axial_direction * half_length * component for component in axis)
    down_projection = (-axis[0] * axis_z, -axis[1] * axis_z, -1.0 + axis_z * axis_z)
    projection_length = math.sqrt(sum(component * component for component in down_projection))
    if projection_length > 1e-15:
        radial = tuple(radius * component / projection_length for component in down_projection)
    else:
        radial = (0.0, 0.0, 0.0)
    return tuple(centre[index] + axial[index] + radial[index] for index in range(3))


def _collision_capable(geom, label):
    try:
        contype = int(geom.get("contype", "1"))
        conaffinity = int(geom.get("conaffinity", "1"))
    except ValueError as error:
        raise CalibrationError(f"{label} contype/conaffinity must be integers") from error
    return not (contype == 0 and conaffinity == 0)


def _geometry_inventory(anchor, source_path, repository_root):
    inventory = []
    direct_geoms = [child for child in list(anchor) if child.tag == "geom"]
    for source_index, geom in enumerate(direct_geoms):
        label = f"geom {source_index} on {anchor.get('name')}"
        geom_type = geom.get("type", "sphere")
        pos = _vector(geom.get("pos"), 3, f"{label} pos", default=(0.0, 0.0, 0.0))
        quat = _vector(geom.get("quat"), 4, f"{label} quat", default=(1.0, 0.0, 0.0, 0.0))
        _normalized_quaternion(quat)
        size_attribute = geom.get("size")
        size = _vector(size_attribute, 2 if geom_type == "cylinder" else len(size_attribute.split()), f"{label} size") if size_attribute else ()
        if geom_type == "cylinder" and len(size) != 2:
            raise CalibrationError(f"{label} cylinder size must contain radius and half-length")
        inventory.append(
            {
                "source_geom_index": source_index,
                "type": geom_type,
                "pos": list(pos),
                "quat_wxyz": list(quat),
                "size": list(size),
                "collision_capable": _collision_capable(geom, label),
                "source_file": source_path.relative_to(repository_root).as_posix(),
            }
        )
    return inventory


def _foot_data(side, anchor, source_path, repository_root):
    inventory = _geometry_inventory(anchor, source_path, repository_root)
    samples = []
    for item in inventory:
        if item["type"] != "cylinder" or not item["collision_capable"]:
            continue
        radius, half_length = item["size"]
        axis = cylinder_axis(item["quat_wxyz"])
        point = cylinder_support_point(item["pos"], item["quat_wxyz"], radius, half_length)
        samples.append(
            {
                "name": f"{side}_sole_{len(samples):02d}",
                "source_geom_index": item["source_geom_index"],
                "body_local_xyz": list(point),
                "radius": radius,
                "half_length": half_length,
                "axis": list(axis),
            }
        )
    if not samples:
        raise CalibrationError(f"anchor {anchor.get('name')} has no collision cylinder sole geometry")
    minimum_z = min(sample["body_local_xyz"][2] for sample in samples)
    return {
        "anchor_body": anchor.get("name"),
        "coordinate_frame": "anchor body-local metres; +Z is the anchor body-local vertical axis",
        "geometry_inventory": inventory,
        "sole_samples": samples,
        "minimum_z": minimum_z,
        "ankle_origin_to_sole_vertical_offset": -minimum_z,
    }


def _anchors_from_sources(sources):
    found = {side: [] for side in ANCHORS}
    for source in sources:
        document = _parse_xml(source)
        for body in document.iter("body"):
            for side, name in ANCHORS.items():
                if body.get("name") == name:
                    found[side].append((body, source))
    resolved = {}
    for side, matches in found.items():
        if len(matches) != 1:
            qualifier = "missing" if not matches else "duplicate"
            raise CalibrationError(f"{qualifier} {ANCHORS[side]} anchor body")
        resolved[side] = matches[0]
    return resolved


def _symmetry_signature(sample):
    point = sample["body_local_xyz"]
    axis = sample["axis"]
    return (
        point[0], abs(point[1]), point[2], sample["radius"], sample["half_length"],
        axis[0], abs(axis[1]), axis[2],
    )


def _validate_symmetry(left, right, tolerance=SYMMETRY_TOLERANCE):
    left_samples = left["sole_samples"]
    right_samples = right["sole_samples"]
    if len(left_samples) != len(right_samples):
        raise CalibrationError("left/right sole sample counts are asymmetric")
    left_signatures = sorted(_symmetry_signature(sample) for sample in left_samples)
    right_signatures = sorted(_symmetry_signature(sample) for sample in right_samples)
    for left_signature, right_signature in zip(left_signatures, right_signatures):
        if any(abs(a - b) > tolerance for a, b in zip(left_signature, right_signature)):
            raise CalibrationError(f"left/right foot geometry differs by more than {tolerance:g} m")


def _configured_ground_clearance(repository_root):
    params_path = Path(repository_root) / "general_motion_retargeting" / "params.py"
    try:
        tree = ast.parse(params_path.read_text(encoding="utf-8"), filename=str(params_path))
    except (OSError, SyntaxError) as error:
        raise CalibrationError(f"could not read configured ground clearance: {error}") from error
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "GROUND_CLEARANCE_DICT" for target in node.targets
        ):
            continue
        try:
            configured = ast.literal_eval(node.value)["linglong2"]
        except (KeyError, ValueError, TypeError) as error:
            raise CalibrationError("GROUND_CLEARANCE_DICT['linglong2'] must be a numeric literal") from error
        if not isinstance(configured, (int, float)) or not math.isfinite(configured):
            raise CalibrationError("GROUND_CLEARANCE_DICT['linglong2'] must be finite")
        return float(configured)
    raise CalibrationError("GROUND_CLEARANCE_DICT is not declared")


def build_calibration(scene_path, repository_root):
    """Build deterministic LingLong2.0 sole geometry and configuration comparison data."""
    root = _resolved(repository_root)
    sources = resolve_mjcf_includes(scene_path, root)
    anchors = _anchors_from_sources(sources)
    feet = {
        side: _foot_data(side, anchor, source, root)
        for side, (anchor, source) in anchors.items()
    }
    _validate_symmetry(feet["left"], feet["right"])
    configured = _configured_ground_clearance(root)
    calibrated = (feet["left"]["ankle_origin_to_sole_vertical_offset"] + feet["right"]["ankle_origin_to_sole_vertical_offset"]) / 2.0
    return {
        "schema_version": 1,
        "deterministic": {
            "robot": "linglong2",
            "scene_path": _repository_path(scene_path, root, "scene path").relative_to(root).as_posix(),
            "source_files": [
                {
                    "path": source.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
                for source in sources
            ],
            "feet": feet,
            "symmetry_tolerance_metres": SYMMETRY_TOLERANCE,
            "ground_clearance_comparison": {
                "configured_value": configured,
                "calibrated_vertical_offset": calibrated,
                "signed_delta_configured_minus_calibrated": configured - calibrated,
                "absolute_delta": abs(configured - calibrated),
                "interpretation": "The configured value remains an initial estimate; this geometric reference does not establish dynamic contact, support, or non-penetration.",
            },
        },
        "runtime_generation_context": {
            "tool": "scripts/calibrate_foot_geometry.py",
            "python_version": sys.version.split()[0],
        },
    }


def _output_is_safe(output_dir, sources):
    output = _resolved(output_dir)
    for source in sources:
        source = _resolved(source)
        if output == source or _inside(output, source) or _inside(source, output):
            raise CalibrationError(f"output path overlaps declared source MJCF {source}")
    return output


def _markdown_summary(calibration):
    deterministic = calibration["deterministic"]
    comparison = deterministic["ground_clearance_comparison"]
    rows = [
        "# LingLong2 Foot Geometry Calibration",
        "",
        "This is a body-local geometry reference in metres, derived from the listed MJCF source files. It is not a dynamic-contact, support, or non-penetration result.",
        "",
        "| Side | Anchor | Minimum local Z | Ankle-origin-to-sole vertical offset | Samples |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for side in ("left", "right"):
        foot = deterministic["feet"][side]
        rows.append(
            f"| {side} | {foot['anchor_body']} | {foot['minimum_z']:.9f} m | "
            f"{foot['ankle_origin_to_sole_vertical_offset']:.9f} m | {len(foot['sole_samples'])} |"
        )
    rows.extend([
        "",
        f"Configured `GROUND_CLEARANCE_DICT['linglong2']`: {comparison['configured_value']:.9f} m.",
        f"Configured minus calibrated offset: {comparison['signed_delta_configured_minus_calibrated']:.9f} m (absolute {comparison['absolute_delta']:.9f} m).",
        "",
        "Later contact metrics should consume the named, source-indexed `sole_samples`; they must not replace this static calibration with an ankle-body origin or infer dynamic contact from it.",
    ])
    return "\n".join(rows) + "\n"


def write_calibration(scene_path, output_dir, repository_root):
    """Write identity-stable JSON and Markdown calibration artifacts."""
    sources = resolve_mjcf_includes(scene_path, repository_root)
    output = _output_is_safe(output_dir, sources)
    calibration = build_calibration(scene_path, repository_root)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "foot-geometry-linglong2.json"
    markdown_path = output / "foot-geometry-linglong2.md"
    json_path.write_text(json.dumps(calibration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown_summary(calibration), encoding="utf-8")
    return {"json_path": json_path, "markdown_path": markdown_path, "calibration": calibration}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene_path", help="repository-bounded MJCF scene path")
    parser.add_argument("output_dir", help="directory for geometry calibration artifacts")
    parser.add_argument(
        "--repository-root", default=Path(__file__).resolve().parents[1], help="repository root for bounded path resolution"
    )
    arguments = parser.parse_args(argv)
    try:
        result = write_calibration(arguments.scene_path, arguments.output_dir, arguments.repository_root)
    except CalibrationError as error:
        parser.error(str(error))
    print(result["json_path"])
    print(result["markdown_path"])
    return 0


if __name__ == "__main__":
    main()
