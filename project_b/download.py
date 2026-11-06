"""Download NYC 311 requests created in calendar 2023 from NYC Open Data.

One Parquet shard per day, every column kept as a raw string so the profiler sees
what the source actually published (including literal "N/A", odd casing and so on).
Re-running skips finished days. Writes a manifest with the snapshot date and row count,
because the source is a live dataset and later downloads can differ slightly.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

ENDPOINT = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
RAW_DIR = Path(__file__).parent / "data" / "raw"
PAGE = 50_000


def _fetch_day(day: dt.date) -> int:
    path = RAW_DIR / f"{day.isoformat()}.parquet"
    if path.exists():
        return len(pd.read_parquet(path, columns=["unique_key"]))
    next_day = day + dt.timedelta(days=1)
    where = f"created_date >= '{day}T00:00:00' AND created_date < '{next_day}T00:00:00'"
    frames, offset = [], 0
    while True:
        params = {"$where": where, "$order": "unique_key", "$limit": PAGE, "$offset": offset}
        for attempt in range(6):
            try:
                resp = requests.get(ENDPOINT, params=params, timeout=180)
                resp.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 5:
                    raise
                time.sleep(2**attempt)
        frame = pd.read_csv(io.StringIO(resp.text), dtype=str, keep_default_na=False, na_values=[""])
        frames.append(frame)
        if len(frame) < PAGE:
            break
        offset += PAGE
    data = pd.concat(frames, ignore_index=True)
    tmp = path.with_suffix(".tmp")
    data.to_parquet(tmp, index=False)
    tmp.rename(path)
    return len(data)


def download(workers: int = 6) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW_DIR.parent / "manifest.json"
    days = [dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(365)]
    with cf.ThreadPoolExecutor(workers) as pool:
        counts = list(pool.map(_fetch_day, days))
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest = {
        "source": ENDPOINT,
        "snapshot_date": previous.get("snapshot_date") or dt.date.today().isoformat(),
        "rows": int(sum(counts)),
        "days": len(days),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(download(), indent=2))
