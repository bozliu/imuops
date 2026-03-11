"""Validated public models for imuops payloads."""

from __future__ import annotations

from typing import Literal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.3"
TRUSTSCORE_VERSION = "v0.3.0"
ARTIFACT_SCHEMA_VERSION = "0.4"


class SessionMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    trustscore_version: str = TRUSTSCORE_VERSION
    dataset: str
    session_id: str
    source_path: str
    task: str = "orientation"
    reference_type: str | None = None
    subject_id: str | None = None
    nominal_hz: float | None = None
    sensors: dict[str, bool] = Field(default_factory=dict)
    labels_available: bool = False
    ground_truth_available: bool = False
    body_location: str | None = None
    device_pose: str | None = None
    label_namespace: str | None = None
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class IssueModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    severity: str
    message: str
    start_ms: int | None = None
    end_ms: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class WindowScoreModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    start_ms: int
    end_ms: int
    trust_score: float
    reason_codes: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)


class AuditSummaryModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    dataset: str
    session_id: str
    task: str
    duration_s: float
    nominal_hz: float
    jitter_ms: float
    trust_score: float
    trustscore_version: str = TRUSTSCORE_VERSION
    status: str = "pass"
    warning_threshold: float
    fail_threshold: float
    window_formula: str | None = None
    session_formula: str | None = None
    missing_gap_count: int = 0
    gps_valid_ratio: float | None = None
    gps_alignment_ratio: float | None = None
    clipping_ratio: float = 0.0
    dropout_ratio: float = 0.0
    gyro_bias_drift_rads: float = 0.0
    pressure_stability_pa: float | None = None
    static_window_ratio: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    penalty_totals: dict[str, float] = Field(default_factory=dict)
    weight_profile: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    window_count: int = 0
    available_sensors: dict[str, bool] = Field(default_factory=dict)
    skipped_checks: list[str] = Field(default_factory=list)


class ReplaySummaryModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    baseline: str
    task: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class BenchmarkBaselineModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    baseline: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class BenchmarkSummaryModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    task: str
    dataset: str
    baselines: list[BenchmarkBaselineModel] = Field(default_factory=list)
    primary_metric_name: str | None = None
    primary_metric_value: float | None = None


class CorruptionSummaryModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    preset: str
    source_session_dir: str
    out_dir: str
    description: str
    modifications: dict[str, Any] = Field(default_factory=dict)


class ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_schema_version: str = ARTIFACT_SCHEMA_VERSION
    artifact_type: str


class ExportCoverageModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    dropped_window_count: int = 0
    dropped_window_reason_counts: dict[str, int] = Field(default_factory=dict)
    requested_reason_codes: list[str] = Field(default_factory=list)


class ExportSummaryModel(ArtifactModel):
    artifact_type: Literal["export_summary"] = "export_summary"

    out_dir: str
    profile: str
    format: str
    removed_rows: int
    kept_rows: int
    threshold_used: float | None = None
    row_counts: dict[str, int] = Field(default_factory=dict)
    written_files: dict[str, str] = Field(default_factory=dict)
    reason_code_coverage: ExportCoverageModel = Field(default_factory=ExportCoverageModel)


class CompareSessionModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    dataset: str
    task: str
    source_path: str | None = None
    subject_id: str | None = None


class CompareSummaryModel(ArtifactModel):
    artifact_type: Literal["compare_summary"] = "compare_summary"

    session_a: CompareSessionModel
    session_b: CompareSessionModel
    trust_score_a: float
    trust_score_b: float
    trust_score_delta: float
    reason_codes_added: list[str] = Field(default_factory=list)
    reason_codes_removed: list[str] = Field(default_factory=list)
    replay_metric_deltas: dict[str, dict[str, float]] = Field(default_factory=dict)
    benchmark_metric_deltas: dict[str, dict[str, float]] = Field(default_factory=dict)
    metadata_differences: dict[str, dict[str, Any]] = Field(default_factory=dict)
    audit_formula: dict[str, Any] = Field(default_factory=dict)
    recommendation_status: str
    recommendation_summary: str
    regression_reasons: list[str] = Field(default_factory=list)
    improvement_reasons: list[str] = Field(default_factory=list)


class BatchRowModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_dir: str
    session_id: str
    dataset: str
    task: str
    trust_score: float
    status: str
    reason_codes: list[str] = Field(default_factory=list)
    rank: int


class ReasonCountModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    count: int


class BatchSummaryModel(ArtifactModel):
    artifact_type: Literal["batch_summary"] = "batch_summary"

    session_count: int
    counts: dict[str, int] = Field(default_factory=dict)
    rows: list[BatchRowModel] = Field(default_factory=list)
    top_reason_codes: dict[str, int] = Field(default_factory=dict)
    reason_code_rows: list[ReasonCountModel] = Field(default_factory=list)


class ValidationCleanModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    trust_score: float
    status: str


class ValidationPresetModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    preset: str
    trust_score: float
    trust_score_delta: float
    non_improving: bool
    baseline_metric_deltas: dict[str, float] = Field(default_factory=dict)


class MetricCorrelationModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    metric: str
    preset_count: int
    average_delta: float
    max_delta: float
    min_delta: float


class TrustScoreValidationSummaryModel(ArtifactModel):
    artifact_type: Literal["trustscore_validation"] = "trustscore_validation"

    session_id: str
    task: str
    clean: ValidationCleanModel
    presets: list[ValidationPresetModel] = Field(default_factory=list)
    all_non_improving: bool = True
    metric_correlation_rows: list[MetricCorrelationModel] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)


class BatchTrustScoreValidationRowModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_dir: str
    session_id: str
    task: str
    all_non_improving: bool
    validation_path: str


class BatchTrustScoreValidationSummaryModel(ArtifactModel):
    artifact_type: Literal["batch_trustscore_validation"] = "batch_trustscore_validation"

    session_count: int
    rows: list[BatchTrustScoreValidationRowModel] = Field(default_factory=list)
    non_improving_count: int = 0
