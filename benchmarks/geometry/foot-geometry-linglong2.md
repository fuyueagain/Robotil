# LingLong2 Foot Geometry Calibration

This is a body-local geometry reference in metres, derived from the listed MJCF source files. It is not a dynamic-contact, support, or non-penetration result.

| Side | Anchor | Minimum local Z | Ankle-origin-to-sole vertical offset | Samples |
| --- | --- | ---: | ---: | ---: |
| left | left_ankle_roll_link | -0.076000547 m | 0.076000547 m | 5 |
| right | right_ankle_roll_link | -0.076000547 m | 0.076000547 m | 5 |

Configured `GROUND_CLEARANCE_DICT['linglong2']`: 0.075000000 m.
Configured minus calibrated offset: -0.001000547 m (absolute 0.001000547 m).

Later contact metrics should consume the named, source-indexed `sole_samples`; they must not replace this static calibration with an ankle-body origin or infer dynamic contact from it.
