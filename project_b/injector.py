"""Inject each of the 12 data-quality problems into a clean batch at a controlled rate.

inject() never mutates its input and is deterministic for a seed. row_labels marks the rows carrying the
problem in the returned frame. For batch_level problems the batch is the unit of detection and row_labels
shows which rows were touched. meta["row_variant"] names each corrupted row's sub-type (None elsewhere),
so recall can be split by how hard the corruption is.

All personal data here is synthetic: phone numbers use the 555-01xx fiction range, emails use example.com,
and names are made up. Held-out paraphrases were written without looking at any detector rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

PROBLEMS = [
    "renamed_dropped_column",
    "type_change",
    "date_format_switch",
    "lat_lon_swap",
    "exact_duplicates",
    "near_duplicates",
    "null_spike",
    "closed_before_created",
    "zip_borough_mismatch",
    "complaint_descriptor_mismatch",
    "resolution_status_contradiction",
    "pii_in_text",
]
BATCH_LEVEL = {"renamed_dropped_column", "type_change", "null_spike"}
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.000"

SCHEMA_TARGETS = {
    "complaint_type": ["Complaint Type", "complaint_typ", "cmplnt_type"],
    "descriptor": ["Descriptor", "descriptor_text", "desc"],
    "created_date": ["Created Date", "created_at", "create_dt"],
    "closed_date": ["Closed Date", "closed_at", "close_dt"],
    "status": ["Status", "request_status", "state"],
    "borough": ["Borough", "boro", "borough_name"],
    "incident_zip": ["Incident Zip", "zip", "zipcode"],
    "latitude": ["Latitude", "lat", "y_lat"],
    "longitude": ["Longitude", "lon", "x_lon"],
    "resolution_description": ["Resolution Description", "resolution", "resolution_text"],
    "agency": ["Agency", "agency_code", "dept"],
}
DATE_FORMATS = ["%m/%d/%Y %I:%M:%S %p", "%d-%m-%Y %H:%M", "%Y/%m/%d %H:%M:%S"]
NULL_SPIKE_COLUMNS = ["resolution_description", "incident_zip", "latitude", "longitude", "location_type", "descriptor", "street_name", "community_board"]

# (text, words in a complaint type that would make the text plausible, so that type is skipped)
NOVEL_DESCRIPTORS = [
    ("Water dripping through bedroom ceiling", ("water", "plumbing", "leak", "paint", "heat", "maintenance", "unsanitary", "door")),
    ("Raccoon trapped in attic vent", ("animal", "rodent", "vent", "wildlife", "unsanitary", "pest")),
    ("Elevator stuck between floors", ("elevator", "building", "general construction")),
    ("Tree roots lifting the pavement", ("tree", "sidewalk", "root", "street condition", "curb")),
    ("Graffiti sprayed on storefront shutter", ("graffiti", "vandal", "dirty", "sanitation")),
    ("Drumming from upstairs tenant all night", ("noise", "music")),
    ("Abandoned boat left on the shoreline", ("abandon", "derelict", "parks", "vessel", "beach")),
]
CLOSED_BUT_PENDING = [
    "Crews have not yet been sent to this location; the matter remains under review.",
    "Work on this request is still underway and no conclusion has been reached.",
    "An inspector will be visiting at a later date; nothing further has happened so far.",
    "We are awaiting a site visit before any action can be taken on your request.",
    "Your report is sitting in the queue for assignment to a field team.",
    "No one has looked at this yet; it will be picked up in the coming days.",
]
OPEN_BUT_DONE = [
    "The crew finished repairs last Tuesday and nothing further is required.",
    "Technicians fixed the problem and your request needs no more attention.",
    "This matter was wrapped up after our staff completed the job on site.",
    "The issue has been taken care of and the file is now finished.",
    "Our team dealt with the condition and the case needs no follow-up.",
]
FIRST_NAMES = ["Priya", "Maria", "Tomasz", "Keisha", "Rahul", "Elena", "Darnell", "Mei", "Yusuf", "Colleen"]
LAST_NAMES = ["Natarajan", "Gonzalez", "Kowalski", "Washington", "Mehrotra", "Petrova", "Fitzgerald", "Okafor", "Lindqvist", "Yamada"]


@dataclass
class Injected:
    batch: pd.DataFrame
    row_labels: np.ndarray
    batch_level: bool
    meta: dict = field(default_factory=dict)


@dataclass
class _Context:
    zip_borough: dict
    zips_by_borough: dict
    pairs: set
    descriptors_by_type: dict
    types: list


_context_cache: dict = {}


def _context(source: pd.DataFrame) -> _Context:
    """Lookups from the reference data. The latest result is kept, because each is costly on a large frame."""
    cached = _context_cache.get(id(source))
    if cached is not None:
        return cached[1]
    table = source[["incident_zip", "borough"]].dropna()
    counts = table.groupby(["incident_zip", "borough"]).size().rename("n").reset_index()
    totals = counts.groupby("incident_zip")["n"].transform("sum")
    top = counts[(counts["n"] / totals >= 0.9) & (totals >= 5 if len(source) > 5000 else totals >= 1)]
    zip_borough = dict(zip(top["incident_zip"], top["borough"]))
    zips_by_borough: dict = {}
    for code, borough in sorted(zip_borough.items()):
        zips_by_borough.setdefault(borough, []).append(code)
    pairs_frame = source[["complaint_type", "descriptor"]].dropna().drop_duplicates()
    pairs = set(zip(pairs_frame["complaint_type"], pairs_frame["descriptor"]))
    descriptors_by_type: dict = {}
    for complaint, descriptor in sorted(pairs):
        descriptors_by_type.setdefault(complaint, []).append(descriptor)
    ctx = _Context(zip_borough, zips_by_borough, pairs, descriptors_by_type, sorted(descriptors_by_type))
    _context_cache.clear()
    _context_cache[id(source)] = (source, ctx)
    return ctx


def _count(rate: float, available: int) -> int:
    return min(available, max(1, round(rate * available))) if available else 0


def _pick(rng: np.random.Generator, candidates: np.ndarray, count: int) -> np.ndarray:
    return np.sort(rng.choice(candidates, size=min(count, len(candidates)), replace=False))


def _object_column(df: pd.DataFrame, column: str) -> np.ndarray:
    return df[column].astype(object).to_numpy(dtype=object, copy=True)


def _assign(df: pd.DataFrame, column: str, values) -> None:
    df[column] = pd.Series(values, index=df.index, dtype=object)


def _set_text(df: pd.DataFrame, column: str, rows: np.ndarray, values: list) -> None:
    """Write text into chosen rows, keeping the column's dtype where every value still fits it."""
    out = _object_column(df, column)
    out[rows] = values
    df[column] = pd.Series(out, index=df.index, dtype=df[column].dtype)


def _result(df: pd.DataFrame, labels: np.ndarray, problem: str, variants=None, **meta) -> Injected:
    row_variant = [None] * len(df)
    if variants:
        for row, name in variants.items():
            row_variant[row] = name
    counts: dict = {}
    for name in (variants or {}).values():
        counts[name] = counts.get(name, 0) + 1
    return Injected(df, labels, problem in BATCH_LEVEL, {"problem": problem, "row_variant": row_variant, "variant_counts": counts, **meta})


def _renamed_dropped(df, rate, rng):
    column = str(rng.choice([c for c in SCHEMA_TARGETS if c in df]))
    labels = np.ones(len(df), dtype=bool)
    if rng.random() < 0.5:
        new_name = str(rng.choice(SCHEMA_TARGETS[column]))
        out = df.rename(columns={column: new_name})
        return _result(out, labels, "renamed_dropped_column", variant="renamed", column=column, new_name=new_name)
    return _result(df.drop(columns=[column]), labels, "renamed_dropped_column", variant="dropped", column=column, new_name=None)


def _type_change(df, rate, rng):
    """A share of a column's values arrives in the wrong type, leaving a mixed column."""
    n = len(df)
    rows = _pick(rng, np.arange(n), _count(rate, n))
    variant = str(rng.choice(["coordinates_as_strings", "key_as_string", "zip_as_float", "date_as_epoch"]))
    labels = np.zeros(n, dtype=bool)
    labels[rows] = True
    if variant == "coordinates_as_strings":
        columns = ["latitude", "longitude"]
        for column in columns:
            out = _object_column(df, column)
            out[rows] = [None if pd.isna(v) else f"{float(v):.6f}" for v in out[rows]]
            _assign(df, column, out)
    elif variant == "key_as_string":
        columns = ["unique_key"]
        out = _object_column(df, "unique_key")
        out[rows] = [f"{int(v)}" for v in out[rows]]
        _assign(df, "unique_key", out)
    elif variant == "zip_as_float":
        columns = ["incident_zip"]
        out = _object_column(df, "incident_zip")
        out[rows] = [None if pd.isna(v) else float(v) for v in out[rows]]
        _assign(df, "incident_zip", out)
    else:
        columns = ["created_date"]
        out = _object_column(df, "created_date")
        out[rows] = [int(pd.Timestamp(v).timestamp()) for v in out[rows]]
        _assign(df, "created_date", out)
    return _result(df, labels, "type_change", variant=variant, columns=columns)


def _date_switch(df, rate, rng):
    """Every row from a point partway through the batch uses another date format."""
    n = len(df)
    count = min(max(1, round(rate * n)), max(n - 1, 1))
    start = n - count
    fmt = str(rng.choice(DATE_FORMATS))
    rows = np.arange(start, n)
    for column in ("created_date", "closed_date"):
        dates = pd.to_datetime(df[column].iloc[start:], format="ISO8601", errors="coerce")
        text = dates.dt.strftime(fmt).astype(object).where(dates.notna(), None)
        _set_text(df, column, rows, list(text))
    labels = np.zeros(n, dtype=bool)
    labels[rows] = True
    return _result(df, labels, "date_format_switch", format=fmt, start_row=int(start))


def _lat_lon_swap(df, rate, rng):
    candidates = np.flatnonzero(df["latitude"].notna().to_numpy() & df["longitude"].notna().to_numpy())
    rows = _pick(rng, candidates, _count(rate, len(df)))
    lat, lon = df["latitude"].to_numpy(copy=True), df["longitude"].to_numpy(copy=True)
    lat[rows], lon[rows] = lon[rows].copy(), lat[rows].copy()
    df["latitude"], df["longitude"] = lat, lon
    labels = np.zeros(len(df), dtype=bool)
    labels[rows] = True
    return _result(df, labels, "lat_lon_swap")


def _insert_after_sources(df, new_rows, sources, rng):
    """Add new rows at random positions after their source rows and return the frame with new-row labels."""
    n = len(df)
    positions = np.concatenate([np.arange(n, dtype=float), sources + rng.random(len(sources)) * (n - sources)])
    combined = pd.concat([df, new_rows], ignore_index=True)
    order = np.argsort(positions, kind="stable")
    labels = np.zeros(len(combined), dtype=bool)
    labels[n:] = True
    return combined.iloc[order].reset_index(drop=True), labels[order], order


def _exact_duplicates(df, rate, rng):
    sources = _pick(rng, np.arange(len(df)), _count(rate, len(df)))
    out, labels, _ = _insert_after_sources(df, df.iloc[sources].copy(), sources, rng)
    return _result(out, labels, "exact_duplicates")


def _typo(text: str, rng: np.random.Generator) -> str:
    if len(text) < 4:
        return text + "x"
    i = int(rng.integers(1, len(text) - 2))
    if text[i] == text[i + 1]:
        return text[:i] + text[i + 1:]
    return text[:i] + text[i + 1] + text[i] + text[i + 2:]


def _shift_timestamp(created: str, closed, rng: np.random.Generator) -> str:
    """Move created_date by up to 3 minutes without placing it after closed_date."""
    seconds = int(rng.integers(5, 181)) * int(rng.choice([-1, 1]))
    moved = pd.Timestamp(created) + pd.Timedelta(seconds=seconds)
    if isinstance(closed, str) and moved.strftime(ISO_FORMAT) > closed:
        moved = pd.Timestamp(created) - pd.Timedelta(seconds=abs(seconds))
    return moved.strftime(ISO_FORMAT)


def _near_duplicates(df, rate, rng):
    sources = _pick(rng, np.arange(len(df)), _count(rate, len(df)))
    new = df.iloc[sources].copy().reset_index(drop=True)
    new["unique_key"] = pd.to_numeric(df["unique_key"]).max() + 1 + np.arange(len(new))
    new = new.astype({c: object for c in ("created_date", "resolution_description", "incident_address")})
    kinds = []
    for i in range(len(new)):
        kind = str(rng.choice(["timestamp", "text", "both"]))
        column = str(rng.choice(["resolution_description", "incident_address"]))
        text = new.at[i, column]
        if kind != "timestamp" and not isinstance(text, str):
            kind = "timestamp"
        if kind in ("timestamp", "both"):
            new.at[i, "created_date"] = _shift_timestamp(new.at[i, "created_date"], new.at[i, "closed_date"], rng)
        if kind in ("text", "both"):
            new.at[i, column] = _typo(text, rng)
        kinds.append(kind)
    new = new.astype({c: df[c].dtype for c in ("created_date", "resolution_description", "incident_address")})
    out, labels, order = _insert_after_sources(df, new, sources, rng)
    positions = {int(old): pos for pos, old in enumerate(order)}
    variants = {positions[len(df) + i]: kinds[i] for i in range(len(new))}
    return _result(out, labels, "near_duplicates", variants)


def _null_spike(df, rate, rng):
    """Null one column for one agency. `rate` is the share of the batch's rows affected, limited by the agency's size."""
    n = len(df)
    counts = df["agency"].value_counts()
    eligible = counts[counts >= max(30, 0.02 * n)]
    agencies = sorted(eligible.index) or sorted(counts.index)
    agency = str(rng.choice(agencies))
    mask = (df["agency"] == agency).to_numpy()
    usable = [c for c in NULL_SPIKE_COLUMNS if c in df and df.loc[mask, c].notna().mean() >= 0.8]
    column = str(rng.choice(usable or [c for c in NULL_SPIKE_COLUMNS if c in df]))
    candidates = np.flatnonzero(mask & df[column].notna().to_numpy())
    rows = _pick(rng, candidates, _count(rate, n))
    values = df[column].copy()
    values.iloc[rows] = np.nan
    df[column] = values
    labels = np.zeros(n, dtype=bool)
    labels[rows] = True
    return _result(df, labels, "null_spike", agency=agency, column=column, agency_null_share=float(df.loc[mask, column].isna().mean()))


def _closed_before_created(df, rate, rng):
    candidates = np.flatnonzero(df["closed_date"].notna().to_numpy())
    rows = _pick(rng, candidates, _count(rate, len(df)))
    created = df["created_date"].to_numpy(dtype=object)
    # Log-uniform from one minute to 30 days, so subtle and obvious errors both occur.
    seconds = np.exp(rng.uniform(np.log(60), np.log(30 * 86400), size=len(rows)))
    values = [(pd.Timestamp(created[r]) - pd.Timedelta(seconds=int(s))).strftime(ISO_FORMAT) for r, s in zip(rows, seconds)]
    _set_text(df, "closed_date", rows, values)
    labels = np.zeros(len(df), dtype=bool)
    labels[rows] = True
    return _result(df, labels, "closed_before_created")


def _zip_borough(df, rate, rng, ctx):
    zips = df["incident_zip"].to_numpy(dtype=object)
    boroughs = df["borough"].to_numpy(dtype=object)
    candidates = np.array([i for i in range(len(df)) if ctx.zip_borough.get(zips[i]) == boroughs[i] and any(b != boroughs[i] for b in ctx.zips_by_borough)], dtype=int)
    rows = _pick(rng, candidates, _count(rate, len(df)))
    values = []
    for row in rows:
        others = sorted(b for b in ctx.zips_by_borough if b != boroughs[row])
        values.append(str(rng.choice(ctx.zips_by_borough[str(rng.choice(others))])))
    _set_text(df, "incident_zip", rows, values)
    labels = np.zeros(len(df), dtype=bool)
    labels[rows] = True
    return _result(df, labels, "zip_borough_mismatch")


def _family(complaint: str) -> str:
    return complaint.lower().replace("-", " ").split()[0] if complaint.strip() else ""


def _complaint_descriptor(df, rate, rng, ctx):
    types = df["complaint_type"].to_numpy(dtype=object)
    candidates = np.array([i for i, t in enumerate(types) if isinstance(t, str)], dtype=int)
    rows = _pick(rng, candidates, _count(rate, len(df)))
    values, variants = [], {}
    for row in rows:
        complaint = types[row]
        kind = str(rng.choice(["never_cooccurring", "sibling", "novel"], p=[0.5, 0.3, 0.2]))
        text = None
        if kind == "novel":
            lowered = complaint.lower()
            options = [t for t, words in NOVEL_DESCRIPTORS if not any(w in lowered for w in words)]
            text = str(rng.choice(options)) if options else None
        if kind == "sibling":
            siblings = [t for t in ctx.types if t != complaint and _family(t) == _family(complaint)]
            options = [d for t in siblings for d in ctx.descriptors_by_type[t] if (complaint, d) not in ctx.pairs]
            text = str(rng.choice(options)) if options else None
        if text is None:
            kind = "never_cooccurring"
            others = [t for t in ctx.types if _family(t) != _family(complaint)] or [t for t in ctx.types if t != complaint]
            for _ in range(50):
                other = str(rng.choice(others))
                option = str(rng.choice(ctx.descriptors_by_type[other]))
                if (complaint, option) not in ctx.pairs:
                    text = option
                    break
            if text is None:
                text = str(rng.choice([t for t, _ in NOVEL_DESCRIPTORS]))
                kind = "novel"
        values.append(text)
        variants[int(row)] = kind
    _set_text(df, "descriptor", rows, values)
    labels = np.zeros(len(df), dtype=bool)
    labels[rows] = True
    return _result(df, labels, "complaint_descriptor_mismatch", variants)


def _resolution_status(df, rate, rng):
    """Text contradicts status. closed_date is kept consistent with status, so only the text gives it away."""
    status = df["status"].to_numpy(dtype=object)
    closed = df["closed_date"].notna().to_numpy()
    has_text = df["resolution_description"].notna().to_numpy()
    candidates = np.flatnonzero((status == "Closed") & closed)
    rows = _pick(rng, candidates, _count(rate, len(df)))
    new_status, new_text, new_closed = status.copy(), _object_column(df, "resolution_description"), _object_column(df, "closed_date")
    variants = {}
    for row in rows:
        kind = str(rng.choice(["status_flip", "closed_but_pending_text", "open_but_done_text"]))
        if kind == "status_flip" and not has_text[row]:
            kind = "closed_but_pending_text"
        if kind == "status_flip":
            new_status[row] = str(rng.choice(["Open", "In Progress"]))
            new_closed[row] = None
        elif kind == "closed_but_pending_text":
            new_text[row] = str(rng.choice(CLOSED_BUT_PENDING))
        else:
            new_status[row] = str(rng.choice(["Open", "In Progress"]))
            new_closed[row] = None
            new_text[row] = str(rng.choice(OPEN_BUT_DONE))
        variants[int(row)] = kind
    df["status"] = pd.Series(new_status, index=df.index, dtype=df["status"].dtype)
    df["resolution_description"] = pd.Series(new_text, index=df.index, dtype=df["resolution_description"].dtype)
    df["closed_date"] = pd.Series(new_closed, index=df.index, dtype=df["closed_date"].dtype)
    labels = np.zeros(len(df), dtype=bool)
    labels[rows] = True
    return _result(df, labels, "resolution_status_contradiction", variants)


def _pii_sentence(kind: str, rng: np.random.Generator) -> str:
    first, last = str(rng.choice(FIRST_NAMES)), str(rng.choice(LAST_NAMES))
    suffix = int(rng.integers(100, 200))
    if kind == "phone":
        return str(rng.choice([f"Caller can be reached at (212) 555-0{suffix}.", f"Call back 917-555-0{suffix} for access.", f"Tenant phone 718.555.0{suffix}."]))
    if kind == "email":
        return str(rng.choice([f"Follow-up sent to {first.lower()}.{last.lower()}{suffix}@example.com.", f"Reply to {first[0].lower()}{last.lower()}@example.org."]))
    if kind == "name_cued":
        return str(rng.choice([f"Complainant name is {first} {last}.", f"My name is {first} {last}.", f"Contact: Ms. {last}."]))
    return str(rng.choice([f"Spoke with {first} {last} about access to the unit.", f"{first} {last} confirmed the condition on site.", f"Inspector met {first} {last} at the front door."]))


def _pii(df, rate, rng):
    rows = _pick(rng, np.arange(len(df)), _count(rate, len(df)))
    text = df["resolution_description"].to_numpy(dtype=object)
    values, variants = [], {}
    for row in rows:
        kind = str(rng.choice(["phone", "email", "name_cued", "name_bare"]))
        sentence = _pii_sentence(kind, rng)
        values.append(f"{text[row]} {sentence}" if isinstance(text[row], str) else sentence)
        variants[int(row)] = kind
    _set_text(df, "resolution_description", rows, values)
    labels = np.zeros(len(df), dtype=bool)
    labels[rows] = True
    return _result(df, labels, "pii_in_text", variants)


def inject(batch: pd.DataFrame, problem: str, rate: float, seed: int, reference: pd.DataFrame | None = None) -> Injected:
    """Return a corrupted copy. `reference` supplies valid ZIPs and pairs; the batch itself is used when it is absent."""
    if problem not in PROBLEMS:
        raise ValueError(f"unknown problem {problem!r}")
    rng = np.random.default_rng([seed, PROBLEMS.index(problem)])
    df = batch.copy(deep=True).reset_index(drop=True)
    if problem == "zip_borough_mismatch":
        return _zip_borough(df, rate, rng, _context(reference if reference is not None else batch))
    if problem == "complaint_descriptor_mismatch":
        return _complaint_descriptor(df, rate, rng, _context(reference if reference is not None else batch))
    simple = {
        "renamed_dropped_column": _renamed_dropped,
        "type_change": _type_change,
        "date_format_switch": _date_switch,
        "lat_lon_swap": _lat_lon_swap,
        "exact_duplicates": _exact_duplicates,
        "near_duplicates": _near_duplicates,
        "null_spike": _null_spike,
        "closed_before_created": _closed_before_created,
        "resolution_status_contradiction": _resolution_status,
        "pii_in_text": _pii,
    }
    return simple[problem](df, rate, rng)
