"""Task 1: profile the raw 2023 data and write results/b_profile.json with counts and real examples.

Works on whichever shards exist and states the coverage. PII-like strings in examples are masked before writing.

Run: python -m project_b.profile_raw
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from project_b.data import LAT_RANGE, LON_RANGE, NYC_ZIP_RE, coverage, load_raw, shard_paths

OUT = Path(__file__).resolve().parent.parent / "results" / "b_profile.json"
COLUMNS = [
    "unique_key", "created_date", "closed_date", "due_date", "resolution_action_updated_date", "agency", "complaint_type",
    "descriptor", "status", "resolution_description", "incident_zip", "borough", "city", "incident_address",
    "latitude", "longitude", "x_coordinate_state_plane", "y_coordinate_state_plane",
]
PLACEHOLDERS = {"n/a", "na", "unknown", "none", "null", "unspecified", "not applicable", "0", "00000", "99999", "-", "--", "."}
PLACEHOLDER_COLUMNS = ["incident_zip", "descriptor", "city", "incident_address", "borough", "agency"]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(?:\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4})(?!\d)")
NAME_CUE_RE = re.compile(r"\b(?:my name is|mr\.|mrs\.|ms\.)\s+[A-Z][a-z]+", re.I)
# Keyword candidates only: the counts are leads to review, not confirmed contradictions.
PENDING_RE = r"has not been|not yet|still (?:open|pending|under)|is being (?:investigated|reviewed)|will be (?:inspected|reviewed|investigated)|under review|in progress|remains open"
DONE_RE = r"has been (?:closed|resolved|completed)|was (?:closed|resolved|completed)|has resolved|took action to fix|issued a summons"
NEAR_DUP_SECONDS = 300
EXAMPLES = 3
EARTH_FEET_TOLERANCE = 3000
PUBLIC_CONTACT_MIN_ROWS = 20


def mask(text):
    if not isinstance(text, str):
        return text
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    return NAME_CUE_RE.sub("[NAME]", text)


def examples(df: pd.DataFrame, rows, columns: list[str]) -> list[dict]:
    picked = df.loc[rows, ["unique_key", *columns]].head(EXAMPLES)
    return [{k: (None if pd.isna(v) else mask(v) if isinstance(v, str) else v) for k, v in row.items()} for row in picked.to_dict("records")]


def finding(df: pd.DataFrame, rows: pd.Series, columns: list[str], note: str = "") -> dict:
    count = int(rows.sum())
    result = {"count": count, "pct": round(100 * count / max(len(df), 1), 3), "examples": examples(df, rows, columns)}
    if note:
        result["note"] = note
    return result


def null_rates_and_row_hashes() -> tuple[dict, dict]:
    """Null counts over all columns, and exact-duplicate counts from a hash of every column except the key."""
    null_counts: dict = {}
    total = 0
    hashes, keys = [], []
    for path in shard_paths():
        shard = pd.read_parquet(path)
        total += len(shard)
        for column, count in shard.isna().sum().items():
            null_counts[column] = null_counts.get(column, 0) + int(count)
        hashes.append(pd.util.hash_pandas_object(shard.drop(columns="unique_key").astype(object), index=False).to_numpy())
        keys.append(shard["unique_key"].to_numpy(dtype=str))
    rates = {c: round(100 * n / total, 2) for c, n in sorted(null_counts.items(), key=lambda kv: -kv[1])}
    row_hashes = pd.Series(np.concatenate(hashes))
    key_series = pd.Series(np.concatenate(keys))
    duplicates = {
        "duplicate_unique_key": int(key_series.duplicated().sum()),
        "same_content_different_key": int(row_hashes.duplicated().sum()),
    }
    return rates, duplicates


def near_duplicates(df: pd.DataFrame) -> pd.Series:
    """Same address, complaint and descriptor within five minutes. Many are separate callers, not bad records."""
    usable = df[df["incident_address"].notna()].copy()
    usable["ts"] = pd.to_datetime(usable["created_date"], format="ISO8601", errors="coerce")
    usable = usable.sort_values(["incident_address", "complaint_type", "descriptor", "ts"])
    same = (
        usable["incident_address"].eq(usable["incident_address"].shift())
        & usable["complaint_type"].eq(usable["complaint_type"].shift())
        & usable["descriptor"].eq(usable["descriptor"].shift())
    )
    close = (usable["ts"] - usable["ts"].shift()).dt.total_seconds() <= NEAR_DUP_SECONDS
    flagged = pd.Series(False, index=df.index)
    flagged.loc[usable.index[same & close]] = True
    return flagged


def state_plane_disagreement(df: pd.DataFrame, lat: pd.Series, lon: pd.Series) -> pd.Series:
    """Fit a linear map from lat/lon to state-plane feet on in-area rows; flag large residuals."""
    x = pd.to_numeric(df["x_coordinate_state_plane"], errors="coerce")
    y = pd.to_numeric(df["y_coordinate_state_plane"], errors="coerce")
    usable = lat.between(*LAT_RANGE) & lon.between(*LON_RANGE) & x.notna() & y.notna()
    if usable.sum() < 100:
        return pd.Series(False, index=df.index)
    design = np.column_stack([lat[usable], lon[usable], np.ones(int(usable.sum()))])
    coef_x, *_ = np.linalg.lstsq(design, x[usable], rcond=None)
    coef_y, *_ = np.linalg.lstsq(design, y[usable], rcond=None)
    distance = np.hypot(design @ coef_x - x[usable], design @ coef_y - y[usable])
    flagged = pd.Series(False, index=df.index)
    flagged.loc[usable[usable].index[distance > EARTH_FEET_TOLERANCE]] = True
    return flagged


def triage_contacts(text: pd.Series, pattern: re.Pattern) -> dict:
    """Separate contacts repeated across many rows (published agency lines) from rare ones that could be personal."""
    found = text.dropna().str.extract(f"({pattern.pattern})", expand=False).dropna()
    # Normalise phones to digits so "(212-639-9675" and "(212) 639-9675" count as one line.
    keys = found.str.replace(r"\D", "", regex=True) if pattern is PHONE_RE else found.str.lower().str.rstrip(".Â")
    counts = keys.value_counts()
    rare = counts[counts < PUBLIC_CONTACT_MIN_ROWS]
    public = counts[counts >= PUBLIC_CONTACT_MIN_ROWS]
    return {
        "rows_with_match": int(len(found)),
        "repeated_contacts": int(len(public)),
        "rows_on_repeated_contacts": int(public.sum()),
        "top_repeated_contacts": {str(k): int(v) for k, v in public.head(5).items()},
        "rare_contacts": int(len(rare)),
        "rows_on_rare_contacts": int(rare.sum()),
        "note": f"Contacts on at least {PUBLIC_CONTACT_MIN_ROWS} rows are treated as published service lines. Rare ones are candidates for manual review, not confirmed personal data.",
    }


def casing_variants(series: pd.Series) -> dict:
    counts = series.dropna().value_counts()
    groups: dict = {}
    for value, count in counts.items():
        groups.setdefault(" ".join(str(value).lower().split()), []).append((str(value), int(count)))
    variants = {k: dict(v) for k, v in groups.items() if len(v) > 1}
    top = sorted(variants.items(), key=lambda kv: -sum(kv[1].values()))
    return {"groups": len(variants), "rows": sum(sum(v.values()) for v in variants.values()), "examples": dict(top[:5])}


def main() -> dict:
    cov = coverage()
    df = load_raw(COLUMNS)
    rows = len(df)
    today = dt.date.today().isoformat()
    report: dict = {
        "coverage": {
            **cov,
            "rows": rows,
            "statement": f"PARTIAL 2023: {cov['days']} of 365 days" if cov["partial_2023"] else "Full calendar year 2023",
        },
        "null_rate_pct_by_column": None,
        "findings": {},
    }
    report["null_rate_pct_by_column"], dups = null_rates_and_row_hashes()
    report["duplicates"] = dups
    findings = report["findings"]

    created, closed = df["created_date"], df["closed_date"]
    due, updated = df["due_date"], df["resolution_action_updated_date"]
    status = df["status"].astype("string").fillna("")
    is_closed = status.eq("Closed").to_numpy()
    findings["closed_before_created"] = finding(df, (closed < created).fillna(False).astype(bool), ["created_date", "closed_date", "agency", "complaint_type"])
    findings["closed_equals_created"] = finding(df, (closed == created).fillna(False).astype(bool), ["created_date", "closed_date", "agency"], "Zero-duration closures. Some may be instant auto-closures.")
    findings["closed_in_future"] = finding(df, (closed > today).fillna(False).astype(bool), ["created_date", "closed_date", "agency", "status"], f"Compared with the run date, {today}.")
    findings["closed_status_without_closed_date"] = finding(df, pd.Series(is_closed & closed.isna().to_numpy(), index=df.index), ["status", "closed_date", "agency", "complaint_type"])
    findings["open_status_with_closed_date"] = finding(df, pd.Series(~is_closed & closed.notna().to_numpy() & status.ne("").to_numpy(), index=df.index), ["status", "closed_date", "agency", "complaint_type"])
    findings["due_before_created"] = finding(df, (due < created).fillna(False).astype(bool), ["created_date", "due_date", "agency"])
    findings["resolution_update_before_created"] = finding(df, (updated < created).fillna(False).astype(bool), ["created_date", "resolution_action_updated_date", "agency"])

    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    findings["missing_coordinates"] = finding(df, lat.isna() | lon.isna(), ["agency", "complaint_type", "incident_zip", "borough"])
    outside = lat.notna() & lon.notna() & ~(lat.between(*LAT_RANGE) & lon.between(*LON_RANGE))
    findings["coordinates_outside_nyc_box"] = finding(df, outside, ["latitude", "longitude", "agency", "borough"])
    findings["lat_lon_vs_state_plane_disagree"] = finding(df, state_plane_disagreement(df, lat, lon), ["latitude", "longitude", "x_coordinate_state_plane", "y_coordinate_state_plane"], f"More than {EARTH_FEET_TOLERANCE} feet from a linear fit.")

    zips = df["incident_zip"].astype("string")
    findings["missing_zip"] = finding(df, zips.isna().fillna(True).astype(bool), ["agency", "complaint_type", "borough"])
    findings["invalid_zip"] = finding(df, (zips.notna() & ~zips.str.fullmatch(NYC_ZIP_RE).fillna(False)).astype(bool), ["incident_zip", "borough", "agency"], "Not a 5-digit NYC-range ZIP. Some are real addresses outside the city.")
    findings["unspecified_borough"] = finding(df, df["borough"].eq("Unspecified").fillna(False).astype(bool), ["borough", "incident_zip", "agency"])

    pair = df[["incident_zip", "borough"]].dropna()
    pair = pair[pair["borough"] != "Unspecified"]
    counts = pair.groupby(["incident_zip", "borough"]).size().rename("n").reset_index()
    counts["share"] = counts["n"] / counts.groupby("incident_zip")["n"].transform("sum")
    majority = counts[(counts["share"] >= 0.9) & (counts.groupby("incident_zip")["n"].transform("sum") >= 20)]
    expected = df["incident_zip"].map(dict(zip(majority["incident_zip"], majority["borough"])))
    inconsistent = expected.notna() & df["borough"].notna() & df["borough"].ne("Unspecified") & df["borough"].ne(expected)
    findings["zip_borough_inconsistent"] = finding(df, inconsistent.astype(bool), ["incident_zip", "borough", "agency"], "Borough differs from one that holds at least 90% of that ZIP's rows.")

    findings["near_duplicates"] = finding(df, near_duplicates(df), ["created_date", "complaint_type", "descriptor", "agency"], f"Same address, complaint and descriptor within {NEAR_DUP_SECONDS}s. Many are separate callers about one incident, which is why this signal alone cannot be a hard rule.")

    midnight = created.str.endswith("T00:00:00.000").fillna(False).astype(bool)
    findings["created_exactly_at_midnight"] = finding(df, midnight, ["created_date", "agency", "complaint_type"], "One minute in 1,440 would be about 0.07% if times were real, so a higher share suggests date-only timestamps.")
    findings["created_exactly_at_midnight"]["top_agencies"] = df.loc[midnight, "agency"].value_counts().head(5).to_dict()

    report["casing_variants"] = {c: casing_variants(df[c]) for c in ("complaint_type", "descriptor", "agency", "city")}

    placeholders: dict = {}
    for column in PLACEHOLDER_COLUMNS:
        lowered = df[column].astype("string").str.strip().str.lower()
        hits = lowered.isin(PLACEHOLDERS).fillna(False).astype(bool)
        placeholders[column] = {"count": int(hits.sum()), "values": df.loc[hits, column].value_counts().head(5).to_dict()}
    report["placeholder_values"] = placeholders

    text = df["resolution_description"].astype("string")
    closed_pending = pd.Series(is_closed, index=df.index) & text.str.contains(PENDING_RE, case=False, regex=True, na=False).astype(bool)
    open_done = pd.Series(status.isin(["Open", "In Progress", "Assigned", "Pending", "Started"]).to_numpy(), index=df.index) & text.str.contains(DONE_RE, case=False, regex=True, na=False).astype(bool)
    findings["closed_status_pending_text_candidates"] = finding(df, closed_pending, ["status", "resolution_description", "agency"], "Keyword candidates, not confirmed contradictions. Templated wording can match.")
    findings["closed_status_pending_text_candidates"]["top_texts"] = {mask(k): int(v) for k, v in df.loc[closed_pending, "resolution_description"].value_counts().head(5).items()}
    findings["open_status_done_text_candidates"] = finding(df, open_done, ["status", "resolution_description", "agency"], "Keyword candidates, not confirmed contradictions. Templated wording can match.")
    findings["open_status_done_text_candidates"]["top_texts"] = {mask(k): int(v) for k, v in df.loc[open_done, "resolution_description"].value_counts().head(5).items()}

    pii_rows = {}
    for column in ("resolution_description", "descriptor", "incident_address"):
        values = df[column].astype("string")
        for name, pattern in (("email", EMAIL_RE), ("phone", PHONE_RE), ("name_cue", NAME_CUE_RE)):
            hits = values.str.contains(pattern.pattern, case=False, regex=True, na=False).astype(bool)
            pii_rows[f"{column}:{name}"] = finding(df, hits, [column, "agency"], "Pattern matches, masked here. A match may be a public agency phone number or email rather than personal data.")
    findings["pii_like_strings"] = pii_rows
    report["pii_triage"] = {name: triage_contacts(text, pattern) for name, pattern in (("phone", PHONE_RE), ("email", EMAIL_RE))}

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, default=str, ensure_ascii=False) + "\n")
    return report


if __name__ == "__main__":
    result = main()
    print(result["coverage"]["statement"], result["coverage"]["rows"], "rows")
    print("duplicates", result["duplicates"])
    for name, item in result["findings"].items():
        if "count" in item:
            print(f"{name}: {item['count']} ({item['pct']}%)")
        else:
            print(name, {k: v["count"] for k, v in item.items()})
