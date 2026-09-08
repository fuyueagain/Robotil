import hashlib
import json
import tempfile
import unittest
from pathlib import Path


try:
    from scripts import build_baseline_report
except ImportError:
    build_baseline_report = None


class BaselineDescriptorValidationTests(unittest.TestCase):
    def test_rejects_a_label_outside_the_two_b84_identities(self):
        self.assertIsNotNone(
            build_baseline_report,
            "baseline report module must be available",
        )
        with self.assertRaises(build_baseline_report.DescriptorError):
            build_baseline_report.validate_descriptor({"identity": "unofficial"})


JOINT_ORDER = [f"joint_{index:02d}" for index in range(30)]


def _descriptor(identity="B84-reproduced"):
    is_reported = identity == "B84-reported"
    return {
        "schema_version": 1,
        "identity": identity,
        "provenance": {
            "kind": "official_submission" if is_reported else "current_code_rerun",
            "description": "hand-checked unittest fixture",
        },
        "input_assumptions": {"source_motion": "fixture only"},
        "robot": "linglong2",
        "model_paths": {
            "mujoco_xml": "assets/LingLong2.0/scene.xml",
            "ik_config": "general_motion_retargeting/ik_configs/smplx_to_linglong2.json",
        },
        "artifacts": [
            {"name": "qpos", "kind": "qpos_csv", "path": "artifacts/qpos.csv"},
            {"name": "metadata", "kind": "retarget_metadata", "path": "artifacts/metadata.json"},
        ],
        "coordinate_conventions": {
            "root_position_slice": "qpos[0:3]",
            "source_quaternion_order": "wxyz",
            "csv_quaternion_order": "xyzw",
            "joint_count": 30,
            "joint_order": JOINT_ORDER,
        },
        "expected": {"fps": 30, "frame_count": 2, "qpos_width": 37},
        "parameters": (
            {
                "smooth_alpha": None,
                "height_adjust": None,
                "root_origin_offset": None,
                "camera_follow": None,
                "ground_clearance": None,
            }
            if is_reported
            else {
                "smooth_alpha": 0.35,
                "height_adjust": True,
                "root_origin_offset": False,
                "camera_follow": True,
                "ground_clearance": 0.075,
            }
        ),
        "commands": {"generation": None if is_reported else "python fixture.py"},
        "known_values": {"fixture": True},
        "unknown_fields": (
            ["commands.generation", "parameters.smooth_alpha"] if is_reported else []
        ),
        "critical_packages": ["definitely-not-an-installed-package"],
    }


def _metadata(robot="linglong2", joint_order=JOINT_ORDER):
    return {
        "robot": robot,
        "qposLength": 37,
        "csvColumns": 37,
        "root": {
            "position": "qpos[0:3]",
            "quatSourceOrder": "wxyz",
            "csvQuatOrder": "xyzw",
        },
        "joints": [
            {"csvIndex": index, "jointName": name}
            for index, name in enumerate(joint_order)
        ],
    }


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(",".join(str(value) for value in row) for row in rows), encoding="utf-8")


class BaselineReportTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.descriptor_path = self.root / "descriptor.json"
        self.output_dir = self.root / "reports"

    def tearDown(self):
        self.temp_directory.cleanup()

    def write_descriptor(self, descriptor):
        self.descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

    def build(self, descriptor=None):
        self.write_descriptor(descriptor or _descriptor())
        return build_baseline_report.build_report(
            self.descriptor_path,
            self.output_dir,
            repository_root=self.root,
        )

    def test_hashes_present_artifacts_and_records_missing_ones(self):
        descriptor = _descriptor()
        descriptor["artifacts"].append(
            {"name": "notes", "kind": "supplementary", "path": "artifacts/notes.txt"}
        )
        notes = self.root / "artifacts" / "notes.txt"
        notes.parent.mkdir()
        notes.write_bytes(b"baseline evidence\n")

        result = self.build(descriptor)
        records = {item["name"]: item for item in result["report"]["artifacts"]}

        self.assertEqual(records["notes"]["size_bytes"], len(b"baseline evidence\n"))
        self.assertEqual(
            records["notes"]["sha256"],
            hashlib.sha256(b"baseline evidence\n").hexdigest(),
        )
        self.assertFalse(records["qpos"]["exists"])
        self.assertIsNone(records["qpos"]["size_bytes"])
        self.assertIsNone(records["qpos"]["sha256"])

    def test_valid_37_column_csv_satisfies_the_contract(self):
        rows = [[float(column) for column in range(37)] for _ in range(2)]
        _write_csv(self.root / "artifacts" / "qpos.csv", rows)

        result = self.build()
        qpos = result["report"]["artifacts"][0]["csv_contract"]

        self.assertTrue(result["report"]["validation"]["passed"])
        self.assertEqual(qpos["row_count"], 2)
        self.assertEqual(qpos["consistent_width"], 37)
        self.assertTrue(qpos["finite_numeric_values"])
        self.assertTrue(qpos["expected_frame_count_match"])
        self.assertTrue(qpos["expected_qpos_width_match"])

    def test_malformed_nonfinite_and_inconsistent_csv_fail_with_details(self):
        cases = {
            "malformed": [["not-a-number"] + [0] * 36],
            "nonfinite": [["nan"] + [0] * 36],
            "inconsistent": [[0] * 37, [0] * 36],
        }
        for name, rows in cases.items():
            with self.subTest(name=name):
                _write_csv(self.root / "artifacts" / "qpos.csv", rows)
                result = self.build()
                errors = result["report"]["validation"]["errors"]
                self.assertFalse(result["report"]["validation"]["passed"])
                self.assertTrue(any(name in error or "row" in error for error in errors))

    def test_metadata_mismatch_fails_the_contract_and_is_reported(self):
        metadata_path = self.root / "artifacts" / "metadata.json"
        metadata_path.parent.mkdir()
        metadata_path.write_text(json.dumps(_metadata(robot="wrong_robot")), encoding="utf-8")

        result = self.build()
        metadata = result["report"]["metadata"]

        self.assertFalse(result["report"]["validation"]["passed"])
        self.assertEqual(metadata["actual"]["robot"], "wrong_robot")
        self.assertTrue(any("metadata robot" in error for error in result["report"]["validation"]["errors"]))

    def test_reported_unknown_history_stays_null(self):
        result = self.build(_descriptor("B84-reported"))
        deterministic = result["report"]["deterministic"]

        self.assertIsNone(deterministic["descriptor"]["parameters"]["smooth_alpha"])
        self.assertIn("parameters.smooth_alpha", deterministic["descriptor"]["unknown_fields"])

    def test_path_traversal_in_an_artifact_is_rejected(self):
        descriptor = _descriptor()
        descriptor["artifacts"][0]["path"] = "../outside.csv"

        with self.assertRaises(build_baseline_report.DescriptorError):
            self.build(descriptor)

    def test_identities_produce_distinct_report_filenames(self):
        reported_path = self.root / "reported.json"
        reproduced_path = self.root / "reproduced.json"
        reported_path.write_text(json.dumps(_descriptor("B84-reported")), encoding="utf-8")
        reproduced_path.write_text(json.dumps(_descriptor("B84-reproduced")), encoding="utf-8")

        reported = build_baseline_report.build_report(
            reported_path, self.output_dir, repository_root=self.root
        )
        reproduced = build_baseline_report.build_report(
            reproduced_path, self.output_dir, repository_root=self.root
        )

        self.assertNotEqual(reported["json_path"].name, reproduced["json_path"].name)
        self.assertNotEqual(reported["markdown_path"].name, reproduced["markdown_path"].name)
        self.assertTrue(reported["json_path"].is_file())
        self.assertTrue(reproduced["markdown_path"].is_file())


if __name__ == "__main__":
    unittest.main()
