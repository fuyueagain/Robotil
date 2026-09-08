import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import calibrate_foot_geometry


def _scene(include_name="robot.xml"):
    return f'<mujoco model="scene"><include file="{include_name}"/></mujoco>'


def _robot(left_geoms, right_geoms):
    return """<mujoco model="robot"><worldbody>
    <body name="left_ankle_roll_link">%s</body>
    <body name="right_ankle_roll_link">%s</body>
    </worldbody></mujoco>""" % (left_geoms, right_geoms)


def _cylinder(pos="0 0 -0.069", size="0.007 0.129", quat=None, extra=""):
    quaternion = "" if quat is None else f' quat="{quat}"'
    return f'<geom type="cylinder" pos="{pos}" size="{size}"{quaternion}{extra}/>'


class FootGeometryCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.scene = self.assets / "scene.xml"
        self.robot = self.assets / "robot.xml"
        config_directory = self.root / "general_motion_retargeting"
        config_directory.mkdir()
        (config_directory / "params.py").write_text(
            'GROUND_CLEARANCE_DICT = {"linglong2": 0.075}\n', encoding="utf-8"
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def write_fixture(self, left_geoms, right_geoms, scene_include="robot.xml"):
        self.scene.write_text(_scene(scene_include), encoding="utf-8")
        self.robot.write_text(_robot(left_geoms, right_geoms), encoding="utf-8")

    def calibration(self):
        return calibrate_foot_geometry.build_calibration(self.scene, self.root)

    def test_resolves_scene_include_relative_to_including_file(self):
        nested = self.assets / "nested"
        nested.mkdir()
        self.scene.write_text(_scene("nested/robot.xml"), encoding="utf-8")
        (nested / "robot.xml").write_text(
            _robot(_cylinder(), _cylinder()), encoding="utf-8"
        )

        sources = calibrate_foot_geometry.resolve_mjcf_includes(self.scene, self.root)

        self.assertEqual([path.relative_to(self.root).as_posix() for path in sources], [
            "assets/scene.xml", "assets/nested/robot.xml"
        ])

    def test_identity_quaternion_defaults_to_local_z_axis(self):
        axis = calibrate_foot_geometry.cylinder_axis((1.0, 0.0, 0.0, 0.0))

        self.assertEqual(axis, (0.0, 0.0, 1.0))

    def test_horizontal_cylinder_minimum_z_is_centre_minus_radius(self):
        # wxyz rotation of +90 degrees around local Y maps cylinder local Z to X.
        result = calibrate_foot_geometry.cylinder_support_point(
            (0.1, 0.2, -0.3), (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0), 0.02, 0.4
        )

        self.assertAlmostEqual(result[2], -0.32, places=12)

    def test_vertical_cylinder_minimum_z_is_centre_minus_half_length(self):
        result = calibrate_foot_geometry.cylinder_support_point(
            (0.1, 0.2, -0.3), (1.0, 0.0, 0.0, 0.0), 0.02, 0.4
        )

        self.assertAlmostEqual(result[2], -0.7, places=12)

    def test_quaternion_is_normalized_before_axis_and_support_are_calculated(self):
        result = calibrate_foot_geometry.cylinder_support_point(
            (0.0, 0.0, 1.0), (2.0, 0.0, 2.0, 0.0), 0.1, 0.3
        )

        self.assertAlmostEqual(result[2], 0.9, places=12)

    def test_tilted_cylinder_support_uses_downward_radial_projection(self):
        # For a +60 degree rotation around Y, axis=(sqrt(3)/2, 0, 1/2).
        # Hand calculation gives axial=(-sqrt(3)/4, 0, -1/4) and radial=
        # (1/5, 0, -sqrt(3)/5) for radius=0.4 and half-length=0.5.
        result = calibrate_foot_geometry.cylinder_support_point(
            (1.0, 2.0, 3.0),
            (0.8660254037844386, 0.0, 0.5, 0.0),
            0.4,
            0.5,
        )

        self.assertAlmostEqual(result[0], 0.7669872981077807, places=12)
        self.assertAlmostEqual(result[1], 2.0, places=12)
        self.assertAlmostEqual(result[2], 2.4035898384862247, places=12)
        radial = (
            result[0] - 1.0 + 0.4330127018922193,
            result[1] - 2.0,
            result[2] - 3.0 + 0.25,
        )
        axis = (0.8660254037844386, 0.0, 0.5)
        self.assertAlmostEqual(sum(a * b for a, b in zip(radial, axis)), 0.0, places=12)

    def test_inventory_distinguishes_visual_mesh_and_collision_cylinders(self):
        left = '<geom type="mesh" contype="0" conaffinity="0" mesh="left-foot"/>' + _cylinder()
        self.write_fixture(left, _cylinder())

        report = self.calibration()
        inventory = report["deterministic"]["feet"]["left"]["geometry_inventory"]

        self.assertEqual(inventory[0]["type"], "mesh")
        self.assertFalse(inventory[0]["collision_capable"])
        self.assertTrue(inventory[1]["collision_capable"])
        self.assertEqual(len(report["deterministic"]["feet"]["left"]["sole_samples"]), 1)

    def test_sole_samples_follow_direct_xml_source_order(self):
        left = _cylinder(pos="1 0 -0.1") + _cylinder(pos="2 0 -0.1", size="0.02 0.1")
        self.write_fixture(left, _cylinder(pos="1 0 -0.1") + _cylinder(pos="2 0 -0.1", size="0.02 0.1"))

        samples = self.calibration()["deterministic"]["feet"]["left"]["sole_samples"]

        self.assertEqual([sample["source_geom_index"] for sample in samples], [0, 1])
        self.assertEqual([sample["name"] for sample in samples], ["left_sole_00", "left_sole_01"])
        self.assertEqual([sample["body_local_xyz"][0] for sample in samples], [1.0, 2.0])

    def test_missing_anchor_and_missing_cylinder_are_rejected(self):
        self.scene.write_text(_scene(), encoding="utf-8")
        self.robot.write_text('<mujoco><worldbody><body name="left_ankle_roll_link"/></worldbody></mujoco>', encoding="utf-8")
        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            self.calibration()

    def test_duplicate_anchor_and_invalid_cylinder_size_are_rejected(self):
        self.scene.write_text(_scene(), encoding="utf-8")
        self.robot.write_text(
            """<mujoco><worldbody>
            <body name="left_ankle_roll_link">%s</body>
            <body name="left_ankle_roll_link">%s</body>
            <body name="right_ankle_roll_link">%s</body>
            </worldbody></mujoco>""" % (_cylinder(), _cylinder(), _cylinder()),
            encoding="utf-8",
        )
        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            self.calibration()

        self.write_fixture(_cylinder(size="not-a-size"), _cylinder())
        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            self.calibration()

        self.robot.write_text(_robot('<geom type="mesh"/>', _cylinder()), encoding="utf-8")
        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            self.calibration()

    def test_include_cycle_and_repository_traversal_are_rejected(self):
        self.scene.write_text(_scene("a.xml"), encoding="utf-8")
        (self.assets / "a.xml").write_text(_scene("scene.xml"), encoding="utf-8")
        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            calibrate_foot_geometry.resolve_mjcf_includes(self.scene, self.root)

        self.scene.write_text(_scene("../outside.xml"), encoding="utf-8")
        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            calibrate_foot_geometry.resolve_mjcf_includes(self.scene, self.root)

    def test_source_output_overlap_is_rejected(self):
        self.write_fixture(_cylinder(), _cylinder())

        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            calibrate_foot_geometry.write_calibration(self.scene, self.assets, self.root)

    def test_left_right_asymmetry_is_rejected(self):
        self.write_fixture(_cylinder(pos="0 0 -0.069"), _cylinder(pos="0 0 -0.060"))

        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            self.calibration()

    def test_symmetry_accepts_reversed_axis_for_same_undirected_cylinder(self):
        left = {
            "sole_samples": [{
                "body_local_xyz": [0.1, -0.2, -0.3],
                "radius": 0.01,
                "half_length": 0.1,
                "axis": [0.6, 0.2, 0.7745966692414834],
            }],
        }
        right = {
            "sole_samples": [{
                "body_local_xyz": [0.1, 0.2, -0.3],
                "radius": 0.01,
                "half_length": 0.1,
                # Mirrored Y axis, then globally reversed: same cylinder axis.
                "axis": [-0.6, 0.2, -0.7745966692414834],
            }],
        }

        calibrate_foot_geometry._validate_symmetry(left, right)

    def test_symmetry_rejects_axis_not_equivalent_under_mirror_or_reversal(self):
        left = {
            "sole_samples": [{
                "body_local_xyz": [0.1, -0.2, -0.3],
                "radius": 0.01,
                "half_length": 0.1,
                "axis": [0.6, 0.2, 0.7745966692414834],
            }],
        }
        right = {
            "sole_samples": [{
                "body_local_xyz": [0.1, 0.2, -0.3],
                "radius": 0.01,
                "half_length": 0.1,
                # Equal component magnitudes, but neither the mirror nor -mirror of left.
                "axis": [0.6, 0.2, -0.7745966692414834],
            }],
        }

        with self.assertRaises(calibrate_foot_geometry.CalibrationError):
            calibrate_foot_geometry._validate_symmetry(left, right)

    def test_real_linglong_scene_has_five_samples_per_side_and_expected_minima(self):
        repository_root = Path(__file__).resolve().parents[1]
        report = calibrate_foot_geometry.build_calibration(
            repository_root / "assets" / "LingLong2.0" / "scene.xml", repository_root
        )

        feet = report["deterministic"]["feet"]
        self.assertEqual(len(feet["left"]["sole_samples"]), 5)
        self.assertEqual(len(feet["right"]["sole_samples"]), 5)
        self.assertAlmostEqual(feet["left"]["minimum_z"], -0.076, places=5)
        self.assertAlmostEqual(feet["right"]["minimum_z"], -0.076, places=5)

    def test_cli_reports_concise_error_without_traceback(self):
        self.scene.write_text('<mujoco><include file="missing.xml"/></mujoco>', encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(Path(calibrate_foot_geometry.__file__)), str(self.scene), str(self.root / "output"), "--repository-root", str(self.root)],
            capture_output=True, text=True, check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_invalid_pos_and_quaternions_without_traceback(self):
        cases = {
            "invalid_pos": _cylinder(pos="not-a-vector"),
            "zero_quaternion": _cylinder(quat="0 0 0 0"),
            "nonfinite_quaternion": _cylinder(quat="nan 0 0 1"),
        }
        for name, invalid_left_geom in cases.items():
            with self.subTest(name=name):
                self.write_fixture(invalid_left_geom, _cylinder())
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(calibrate_foot_geometry.__file__)),
                        str(self.scene),
                        str(self.root / "output"),
                        "--repository-root",
                        str(self.root),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_writer_emits_identity_stable_json_and_markdown(self):
        self.write_fixture(_cylinder(), _cylinder())

        result = calibrate_foot_geometry.write_calibration(self.scene, self.root / "output", self.root)

        self.assertEqual(result["json_path"].name, "foot-geometry-linglong2.json")
        self.assertEqual(result["markdown_path"].name, "foot-geometry-linglong2.md")
        self.assertEqual(json.loads(result["json_path"].read_text(encoding="utf-8"))["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
