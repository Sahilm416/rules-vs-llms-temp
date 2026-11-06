"""Shared detector interface, and helpers that stay safe when a column has been dropped or retyped."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BATCH_PROBLEMS = {"renamed_dropped_column", "type_change", "date_format_switch", "null_spike"}
DATE_COLUMNS = ("created_date", "closed_date", "due_date", "resolution_action_updated_date")
NUMERIC_COLUMNS = ("latitude", "longitude", "x_coordinate_state_plane", "y_coordinate_state_plane", "unique_key", "incident_zip")
MAX_ALERT_ROWS = 20


@dataclass
class Alert:
    problem: str
    family: str
    rows: list
    columns: list
    observed: str
    expected: str
    reason: str


@dataclass
class DetectionResult:
    row_flags: np.ndarray
    batch_alert: bool
    alerts: list = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    model: str | None = None
    reviewed_rows: int = 0


class Detector:
    problem = ""
    family = ""

    def fit(self, reference: pd.DataFrame) -> "Detector":
        return self

    def detect(self, batch: pd.DataFrame) -> DetectionResult:
        raise NotImplementedError

    def _empty(self, batch: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(batch), dtype=bool)

    def _result(self, batch, flags, columns, observed, expected, reason, alert=None) -> DetectionResult:
        """Build one alert from row flags. `alert` overrides the default of alerting when any row is flagged."""
        flags = np.asarray(flags, dtype=bool)
        fired = bool(flags.any()) if alert is None else bool(alert)
        alerts = []
        if fired:
            rows = [int(i) for i in np.flatnonzero(flags)[:MAX_ALERT_ROWS]]
            alerts.append(Alert(self.problem, self.family, rows, list(columns), str(observed), str(expected), str(reason)))
        return DetectionResult(flags, fired, alerts)


def text(batch: pd.DataFrame, name: str) -> pd.Series:
    """Column as object strings with missing values preserved. An absent column reads as all missing."""
    if name not in batch.columns:
        return pd.Series([None] * len(batch), index=batch.index, dtype=object)
    series = batch[name]
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.strftime("%Y-%m-%dT%H:%M:%S.000").astype(object).where(series.notna(), None)
    return series.astype(object).where(series.notna(), None).map(lambda v: None if v is None else str(v))


def number(batch: pd.DataFrame, name: str) -> pd.Series:
    if name not in batch.columns:
        return pd.Series(np.nan, index=batch.index, dtype=float)
    return pd.to_numeric(batch[name], errors="coerce")


def when(batch: pd.DataFrame, name: str) -> pd.Series:
    """Parse ISO timestamps. Other formats become NaT, and are the date-format detector's job."""
    if name not in batch.columns:
        return pd.Series(pd.NaT, index=batch.index, dtype="datetime64[ns]")
    series = batch[name]
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, format="ISO8601", errors="coerce")


def mask_of(value) -> str:
    """Character-class shape: '2023-01-05T10:00:00.000' -> 'dddd-dd-ddTdd:dd:dd.ddd'."""
    if value is None:
        return ""
    out = []
    for ch in str(value):
        if ch.isdigit():
            out.append("d")
        elif ch.isalpha():
            out.append("T" if ch == "T" else "a")
        else:
            out.append(ch)
    return "".join(out)


def sample_reference(reference: pd.DataFrame, n: int = 200_000, seed: int = 7) -> pd.DataFrame:
    return reference if len(reference) <= n else reference.sample(n, random_state=seed)


def chunks(frame: pd.DataFrame, size: int = 5000, limit: int = 30, seed: int = 11) -> list[pd.DataFrame]:
    """Random reference chunks shaped like production batches, for threshold calibration."""
    rng = np.random.default_rng(seed)
    count = min(limit, max(len(frame) // size, 1))
    order = rng.permutation(len(frame))
    return [frame.iloc[order[i * size : (i + 1) * size]] for i in range(count)]
