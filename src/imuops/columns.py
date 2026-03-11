"""Canonical dataframe column definitions."""

IMU_COLUMNS = [
    "t_ms",
    "ax",
    "ay",
    "az",
    "gx",
    "gy",
    "gz",
    "mx",
    "my",
    "mz",
    "temp_c",
    "pressure_pa",
    "activity_label",
]

GPS_COLUMNS = [
    "t_ms",
    "lat",
    "lon",
    "valid",
    "raw_sentence",
]

GROUND_TRUTH_COLUMNS = [
    "t_ms",
    "x",
    "y",
    "z",
    "heading",
]

REPLAY_COLUMNS = [
    "t_ms",
    "qw",
    "qx",
    "qy",
    "qz",
    "roll",
    "pitch",
    "yaw",
    "x",
    "y",
]

