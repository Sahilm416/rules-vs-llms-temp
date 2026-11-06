"""Load the raw 311 shards and build the reference and evaluation splits.

clean() scrubs rows with real quality problems so that injected problems are the only ground truth.
False-alarm rates on clean batches are therefore measured on scrubbed data: they show the alarms a
detector raises on well-formed rows, not how it behaves on raw data. Real issues are reported separately.

The code uses whichever daily shards exist and names cache files by day count, so partial and full
downloads never share a cache.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "raw"
FLOAT_COLUMNS = ("latitude", "longitude", "x_coordinate_state_plane", "y_coordinate_state_plane")
DATE_COLUMNS = ("created_date", "closed_date", "due_date", "resolution_action_updated_date")
LAT_RANGE = (40.45, 40.95)
LON_RANGE = (-74.30, -73.65)
NYC_ZIP_RE = r"^1(?:0[0-4]|1[0-6])\d{2}$"
REFERENCE_SHARE = 0.70


def shard_paths() -> list[Path]:
    return sorted(RAW_DIR.glob("*.parquet"))


def coverage() -> dict:
    """Which days are on disk, and whether the finished-download manifest exists."""
    paths = shard_paths()
    manifest_path = DATA_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    return {
        "days": len(paths),
        "first_day": paths[0].stem if paths else None,
        "last_day": paths[-1].stem if paths else None,
        "manifest": manifest,
        "partial_2023": manifest is None or len(paths) < 365,
    }


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    order = np.lexsort((pd.to_numeric(frame["unique_key"]).to_numpy(), frame["created_date"].to_numpy(dtype=str)))
    return frame.iloc[order].reset_index(drop=True)


def load_raw(columns: list[str] | None = None, paths: list[Path] | None = None) -> pd.DataFrame:
    """All columns as raw strings, sorted by created_date then numeric unique_key."""
    wanted = None if columns is None else list(dict.fromkeys(["unique_key", "created_date", *columns]))
    frames = [pd.read_parquet(p, columns=wanted) for p in (paths if paths is not None else shard_paths())]
    if not frames:
        raise FileNotFoundError(f"no shards in {RAW_DIR}; run python -m project_b.download")
    data = _sorted(pd.concat(frames, ignore_index=True))
    return data if columns is None else data[list(columns)]


def typed(df: pd.DataFrame) -> pd.DataFrame:
    """Copy with unique_key as int64 and coordinates as float64. Dates stay as ISO strings."""
    out = df.copy()
    out["unique_key"] = pd.to_numeric(out["unique_key"]).astype("int64")
    for column in FLOAT_COLUMNS:
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce").astype("float64")
    return out


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with real issues that would contaminate ground truth; see the module docstring."""
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    closed, created = df["closed_date"], df["created_date"]
    keep = (
        lat.between(*LAT_RANGE)
        & lon.between(*LON_RANGE)
        & df["incident_zip"].astype("string").str.fullmatch(NYC_ZIP_RE).fillna(False).astype(bool)
        & df["borough"].notna()
        & (df["borough"] != "Unspecified")
        & ~(closed.notna() & (closed < created)).astype(bool)
        & ~df["unique_key"].duplicated(keep="first")
    )
    return df.loc[keep].reset_index(drop=True)


def splits() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(reference, eval): cleaned and typed, first 70% of available days against the last 30%, with no overlap."""
    paths = shard_paths()
    if not paths:
        raise FileNotFoundError(f"no shards in {RAW_DIR}; run python -m project_b.download")
    reference_path = DATA_DIR / f"splits_reference_{len(paths)}d.parquet"
    eval_path = DATA_DIR / f"splits_eval_{len(paths)}d.parquet"
    if reference_path.exists() and eval_path.exists():
        return pd.read_parquet(reference_path), pd.read_parquet(eval_path)
    cut = max(1, min(len(paths) - 1, int(len(paths) * REFERENCE_SHARE)))
    if len(paths) == 1:
        raise ValueError("at least two days of data are needed to split")
    reference = typed(clean(load_raw(paths=paths[:cut])))
    evaluation = typed(clean(load_raw(paths=paths[cut:])))
    for frame, path in ((reference, reference_path), (evaluation, eval_path)):
        tmp = path.with_suffix(f".{os.getpid()}.tmp")  # atomic, because another process may read this cache
        frame.to_parquet(tmp, index=False)
        tmp.rename(path)
    for old in DATA_DIR.glob("splits_*.parquet"):
        if old not in (reference_path, eval_path):
            old.unlink(missing_ok=True)
    return reference, evaluation


def clean_batches(eval_df: pd.DataFrame, n: int, size: int, seed: int) -> list[pd.DataFrame]:
    """n non-overlapping batches of consecutive rows at seeded positions.

    Consecutive rows keep real arrival behaviour, including several callers reporting one incident,
    which random sampling would hide from duplicate detectors.
    """
    if n * size > len(eval_df):
        raise ValueError(f"{n} batches of {size} need {n * size} rows; eval_df has {len(eval_df)}")
    rng = np.random.default_rng(seed)
    spare = len(eval_df) - n * size
    gaps = np.sort(rng.integers(0, spare + 1, size=n))
    return [eval_df.iloc[i * size + gaps[i] : (i + 1) * size + gaps[i]].reset_index(drop=True).copy() for i in range(n)]
