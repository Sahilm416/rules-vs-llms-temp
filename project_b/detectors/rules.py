"""Family (a): declarative rules and schema checks. Lookup tables are frozen from the reference period."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from project_b.detectors.base import DATE_COLUMNS, DetectionResult, Detector, number, text, when

LAT_RANGE, LON_RANGE = (40.45, 40.95), (-74.30, -73.65)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")
OPEN_STATUSES = {"Open", "In Progress", "Pending", "Assigned", "Started"}
# Wording that says work is finished, or that it is still to come. Deliberately excludes "still open",
# which real duplicate-complaint resolutions use about a different complaint while correctly Closed.
FINISHED_RE = re.compile(
    r"complaint has been closed|took action to fix|issued a summons|no evidence of the violation|found no (?:condition|violation)|repaired the problem"
    r"|collected the requested|cleaned the location|work (?:is|was|has been) (?:completed|complete|finished)|has been (?:resolved|completed|closed)|were corrected",
    re.I,
)
PENDING_RE = re.compile(
    r"will (?:visit|inspect|investigate|address|contact)|is reviewing|has been submitted|please check back later|further investigation is required|work order"
    r"|has received your complaint|not yet|remains? (?:open|pending|unresolved)|still (?:pending|under review|being investigated)|awaiting|in progress",
    re.I,
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)|(?<!\d)\d{10}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
NAME_RE = re.compile(r"\b(?i:(?:my |complainant )?name is|caller(?: name)?(?: is)?:?|contact:?|name:|mr\.?|mrs\.?|ms\.?|dr\.?)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")


def _kind(value) -> str:
    return "number" if isinstance(value, (int, float, np.number)) and not isinstance(value, bool) else "string"


class SchemaRule(Detector):
    problem, family = "renamed_dropped_column", "rules"

    def fit(self, reference):
        self.columns = list(reference.columns)
        return self

    def detect(self, batch):
        missing = sorted(set(self.columns) - set(batch.columns))
        extra = sorted(set(batch.columns) - set(self.columns))
        return self._result(
            batch, self._empty(batch), missing + extra, f"missing={missing} unexpected={extra}", f"exactly the {len(self.columns)} contracted columns",
            "Batch columns differ from the contracted schema", alert=bool(missing or extra),
        )


class TypeRule(Detector):
    problem, family = "type_change", "rules"
    PATTERNS = {
        "latitude": r"^-?\d+\.\d+$", "longitude": r"^-?\d+\.\d+$", "unique_key": r"^\d+$", "incident_zip": r"^.{5}$",
        "x_coordinate_state_plane": r"^\d+(\.0+)?$", "y_coordinate_state_plane": r"^\d+(\.0+)?$",
    }

    def fit(self, reference):
        self.dtypes = {c: str(reference[c].dtype) for c in reference.columns}
        self.kinds = {c: _kind(reference[c].dropna().iloc[0]) for c in (*self.PATTERNS, "created_date") if c in reference.columns and reference[c].notna().any()}
        return self

    def detect(self, batch):
        flags, bad, shown = self._empty(batch), [], ""
        for col in (*self.PATTERNS, "created_date"):
            if col not in batch.columns:
                continue
            pattern = self.PATTERNS.get(col, r"^.+$")
            values = text(batch, col)
            present = values.notna().to_numpy()
            matched = values.fillna("").str.match(pattern).to_numpy()
            wrong_kind = np.fromiter((v is not None and v == v and _kind(v) != self.kinds.get(col) for v in batch[col].astype(object)), dtype=bool, count=len(batch))
            failing = present & (~matched | wrong_kind)
            dtype_changed = self.dtypes.get(col) != str(batch[col].dtype)
            if failing.any() or dtype_changed:
                bad.append(col)
                flags |= failing
                sample = values[failing].head(1).tolist()
                shown += f"{col}: dtype={batch[col].dtype} (contract {self.dtypes.get(col)}), {int(failing.sum())} values fail format, e.g. {sample}; "
        return self._result(batch, flags, bad, shown, "each column's contracted type and format", "Values do not match the declared column type", alert=bool(bad))


class DateFormatRule(Detector):
    problem, family = "date_format_switch", "rules"

    def detect(self, batch):
        flags, bad, shown = self._empty(batch), [], ""
        for col in DATE_COLUMNS:
            if col not in batch.columns or pd.api.types.is_datetime64_any_dtype(batch[col]):
                continue
            values = text(batch, col)
            failing = values.notna().to_numpy() & ~values.fillna("").str.match(ISO_RE).to_numpy()
            if failing.any():
                flags |= failing
                bad.append(col)
                first = int(np.flatnonzero(failing)[0])
                shown += f"{col}: {int(failing.sum())} non-ISO values from row {first}, e.g. {values.iloc[first]!r}; "
        return self._result(batch, flags, bad, shown, "ISO 8601 such as 2023-01-05T10:00:00.000", "Date values do not match the ISO format")


class CoordinateRule(Detector):
    problem, family = "lat_lon_swap", "rules"

    def detect(self, batch):
        lat, lon = number(batch, "latitude"), number(batch, "longitude")
        present = lat.notna() & lon.notna()
        inside = lat.between(*LAT_RANGE) & lon.between(*LON_RANGE)
        flags = (present & ~inside).to_numpy()
        return self._result(
            batch, flags, ["latitude", "longitude"], f"e.g. lat={lat[flags].head(1).tolist()} lon={lon[flags].head(1).tolist()}",
            f"lat in {LAT_RANGE}, lon in {LON_RANGE}", "Coordinates fall outside New York City, which usually means they are swapped",
        )


class ExactDuplicateRule(Detector):
    problem, family = "exact_duplicates", "rules"

    def detect(self, batch):
        flags = batch.astype(str).duplicated(keep="first").to_numpy()
        return self._result(batch, flags, ["all columns"], f"{int(flags.sum())} rows repeat an earlier row in full", "every row unique", "Row is a byte-for-byte repeat of an earlier row")


class NearDuplicateRule(Detector):
    """Same coordinates, complaint and descriptor, a different unique key, within a short window. Both rows are flagged."""

    problem, family = "near_duplicates", "rules"
    WINDOW_SECONDS = 180

    def detect(self, batch):
        frame = pd.DataFrame({
            "pos": np.arange(len(batch)), "lat": number(batch, "latitude").to_numpy(), "lon": number(batch, "longitude").to_numpy(),
            "type": text(batch, "complaint_type").to_numpy(), "desc": text(batch, "descriptor").to_numpy(),
            "created": when(batch, "created_date").to_numpy(), "key": text(batch, "unique_key").to_numpy(),
        }).dropna(subset=["lat", "lon", "type", "created"]).sort_values(["lat", "lon", "type", "desc", "created"])
        flags = self._empty(batch)
        same = (frame["lat"] == frame["lat"].shift()) & (frame["lon"] == frame["lon"].shift()) & (frame["type"] == frame["type"].shift()) & (frame["desc"] == frame["desc"].shift())
        gap = (frame["created"] - frame["created"].shift()).dt.total_seconds()
        hit = (same & (gap <= self.WINDOW_SECONDS) & (frame["key"] != frame["key"].shift())).to_numpy()
        positions = frame["pos"].to_numpy()
        flags[positions[hit]] = True
        flags[positions[np.flatnonzero(hit) - 1]] = True
        return self._result(batch, flags, ["latitude", "longitude", "complaint_type", "descriptor", "created_date"], f"{int(flags.sum())} rows in pairs", f"no repeat at one location and complaint within {self.WINDOW_SECONDS}s", "Same location and complaint filed moments apart under a new key")


class NullSpikeRule(Detector):
    problem, family = "null_spike", "rules"
    TOLERANCE = 0.30
    MIN_ROWS = 100

    def fit(self, reference):
        # Lifecycle columns are null until a request finishes, so their rate depends on request age, not data quality.
        self.columns = [c for c in reference.columns if c not in ("agency", "agency_name", "unique_key", "created_date", "closed_date", "resolution_action_updated_date")]
        nulls = reference[self.columns].isna()
        self.limits = nulls.groupby(reference["agency"].to_numpy()).mean()
        return self

    def detect(self, batch):
        flags, findings, cols = self._empty(batch), [], []
        if "agency" not in batch.columns:
            return DetectionResult(flags, False, [])
        agency = batch["agency"].to_numpy()
        for name, idx in batch.groupby("agency", sort=False).indices.items():
            if len(idx) < self.MIN_ROWS or name not in self.limits.index:
                continue
            for col in self.columns:
                if col not in batch.columns:
                    continue
                rate = float(batch[col].iloc[idx].isna().mean())
                limit = float(self.limits.at[name, col])
                if rate > limit + self.TOLERANCE:
                    findings.append(f"{name}.{col} null rate {rate:.0%} vs baseline {limit:.0%}")
                    cols.append(col)
                    flags[idx] |= batch[col].iloc[idx].isna().to_numpy()
        return self._result(batch, flags, sorted(set(cols)), "; ".join(findings[:5]), f"null rate within {self.TOLERANCE:.0%} of the agency's baseline", "An agency's null rate jumped past its limit", alert=bool(findings))


class ClosedBeforeCreatedRule(Detector):
    problem, family = "closed_before_created", "rules"

    def detect(self, batch):
        created, closed = when(batch, "created_date"), when(batch, "closed_date")
        flags = (closed < created).to_numpy()
        first = np.flatnonzero(flags)[:1]
        seen = f"created={created.iloc[first[0]]} closed={closed.iloc[first[0]]}" if len(first) else ""
        return self._result(batch, flags, ["created_date", "closed_date"], seen, "closed_date on or after created_date", "Request closed before it was created")


class ZipBoroughRule(Detector):
    problem, family = "zip_borough_mismatch", "rules"
    MIN_SHARE = 0.01

    def fit(self, reference):
        pairs = pd.DataFrame({"zip": text(reference, "incident_zip"), "borough": text(reference, "borough")}).dropna()
        pairs = pairs[pairs["borough"] != "Unspecified"]
        share = pairs.groupby("zip")["borough"].value_counts(normalize=True)
        self.allowed = {}
        for (zip_code, borough), value in share.items():
            if value >= self.MIN_SHARE:
                self.allowed.setdefault(zip_code, set()).add(borough)
        return self

    def detect(self, batch):
        zips, boroughs = text(batch, "incident_zip").to_numpy(), text(batch, "borough").to_numpy()
        flags = self._empty(batch)
        for i, (z, b) in enumerate(zip(zips, boroughs)):
            if z in self.allowed and b not in (None, "Unspecified") and b not in self.allowed[z]:
                flags[i] = True
        first = np.flatnonzero(flags)[:1]
        seen = f"zip {zips[first[0]]} with borough {boroughs[first[0]]}" if len(first) else ""
        expected = f"borough in {sorted(self.allowed.get(zips[first[0]], []))}" if len(first) else "borough allowed for the zip"
        return self._result(batch, flags, ["incident_zip", "borough"], seen, expected, "Borough is not one this ZIP belongs to")


class ComplaintDescriptorRule(Detector):
    problem, family = "complaint_descriptor_mismatch", "rules"
    MIN_COUNT = 1

    def fit(self, reference):
        counts = pd.DataFrame({"t": text(reference, "complaint_type"), "d": text(reference, "descriptor")}).dropna().value_counts()
        self.allowed = {pair for pair, n in counts.items() if n >= self.MIN_COUNT}
        return self

    def detect(self, batch):
        types, descs = text(batch, "complaint_type").to_numpy(), text(batch, "descriptor").to_numpy()
        flags = np.array([t is not None and d is not None and (t, d) not in self.allowed for t, d in zip(types, descs)], dtype=bool)
        first = np.flatnonzero(flags)[:1]
        seen = f"{types[first[0]]!r} with {descs[first[0]]!r}" if len(first) else ""
        return self._result(batch, flags, ["complaint_type", "descriptor"], seen, "a pair on the allow-list from the reference period", "This complaint type was never seen with this descriptor")


class ResolutionStatusRule(Detector):
    problem, family = "resolution_status_contradiction", "rules"

    def detect(self, batch):
        status, res = text(batch, "status").to_numpy(), text(batch, "resolution_description").fillna("")
        finished, pending = res.str.contains(FINISHED_RE).to_numpy(), res.str.contains(PENDING_RE).to_numpy()
        is_open = np.isin(status.astype(str), list(OPEN_STATUSES))
        is_closed = status.astype(str) == "Closed"
        flags = (is_open & finished & ~pending) | (is_closed & pending & ~finished)
        first = np.flatnonzero(flags)[:1]
        seen = f"status={status[first[0]]}, text={res.iloc[first[0]][:90]!r}" if len(first) else ""
        return self._result(batch, flags, ["status", "resolution_description"], seen, "status agreeing with the resolution wording", "Resolution wording contradicts the status")


class PiiRule(Detector):
    problem, family = "pii_in_text", "rules"
    COLUMNS = ("descriptor", "resolution_description")
    PATTERNS = (("email", EMAIL_RE), ("phone", PHONE_RE), ("ssn", SSN_RE), ("name", NAME_RE))
    INSTITUTIONAL_MIN_COUNT = 5

    def fit(self, reference):
        """Agency help lines and mailboxes repeat across templated text, so frequent matches are not personal data."""
        counts: dict = {}
        for col in self.COLUMNS:
            for value, n in text(reference, col).dropna().value_counts().items():
                for _, pattern in self.PATTERNS:
                    for match in pattern.finditer(value):
                        counts[match.group(0)] = counts.get(match.group(0), 0) + n
        self.institutional = {m for m, n in counts.items() if n >= self.INSTITUTIONAL_MIN_COUNT}
        return self

    def _has_new_match(self, value: str, pattern) -> bool:
        return any(m.group(0) not in self.institutional for m in pattern.finditer(value))

    def detect(self, batch):
        flags, kinds, shown = self._empty(batch), set(), ""
        for col in self.COLUMNS:
            values = text(batch, col).fillna("")
            for kind, pattern in self.PATTERNS:
                hits = values.map(lambda v, p=pattern: self._has_new_match(v, p)).to_numpy(dtype=bool)
                if hits.any():
                    flags |= hits
                    kinds.add(kind)
                    shown = shown or f"{kind} pattern in {col} at row {int(np.flatnonzero(hits)[0])} (value withheld from the alert)"
        return self._result(batch, flags, list(self.COLUMNS), shown, "no personal data in free text", f"Free text matches personal-data patterns: {sorted(kinds)}")


ALL = [SchemaRule, TypeRule, DateFormatRule, CoordinateRule, ExactDuplicateRule, NearDuplicateRule, NullSpikeRule, ClosedBeforeCreatedRule, ZipBoroughRule, ComplaintDescriptorRule, ResolutionStatusRule, PiiRule]
