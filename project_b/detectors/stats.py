"""Family (b): statistical and ML detectors. Every threshold is calibrated on reference data only."""
from __future__ import annotations

import re
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier

from project_b.detectors.base import DATE_COLUMNS, Detector, chunks, mask_of, number, sample_reference, text, when

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']+")
CONTACT_RE = re.compile(r"[\w.+-]+@[\w.-]+|\(?\d{3}\)?[-. ]*\d{3}[-. ]*\d{4}")


def _profile(series: pd.Series) -> np.ndarray:
    values = series.dropna().astype(str)
    if values.empty:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return np.array([series.isna().mean(), values.str.len().mean() / 50, values.nunique() / max(len(values), 1), values.str.contains(r"\d", regex=True).mean()])


class FingerprintStat(Detector):
    """Compare value profiles, so a rename shows up as an absent profile plus an orphan that resembles it."""

    problem, family = "renamed_dropped_column", "stats"

    def fit(self, reference):
        sample = sample_reference(reference, 20000)
        self.profiles = {c: _profile(sample[c]) for c in sample.columns}
        return self

    def detect(self, batch):
        absent = [c for c in self.profiles if c not in batch.columns]
        orphans = [c for c in batch.columns if c not in self.profiles]
        matches = []
        for orphan in orphans:
            prof = _profile(batch[orphan])
            best = min(absent or list(self.profiles), key=lambda c: np.abs(self.profiles[c] - prof).sum())
            matches.append(f"{orphan}~{best}")
        return self._result(batch, self._empty(batch), absent + orphans, f"profiles absent: {absent}; unmatched columns: {matches}", f"{len(self.profiles)} known column profiles", "Column value profiles no longer match the reference", alert=bool(absent or orphans))


class TypeShareStat(Detector):
    """Share of values per column with a character shape that was rare in the reference."""

    problem, family = "type_change", "stats"
    COLUMNS = ("latitude", "longitude", "unique_key", "incident_zip", "x_coordinate_state_plane", "y_coordinate_state_plane", "bbl", "created_date")
    RARE = 0.0005

    @staticmethod
    def _is_number(series: pd.Series) -> np.ndarray:
        return np.fromiter((isinstance(v, (int, float, np.number)) and v == v for v in series.astype(object)), dtype=bool, count=len(series))

    def fit(self, reference):
        sample = sample_reference(reference, 100000)
        self.known, self.limit = {}, {}
        for col in self.COLUMNS:
            if col not in sample.columns:
                continue
            shapes = text(sample, col).dropna().map(mask_of).value_counts(normalize=True)
            self.known[col] = set(shapes[shapes >= self.RARE].index)
            shares = [(~text(c, col).dropna().map(mask_of).isin(self.known[col])).mean() for c in chunks(sample, 5000, 15)]
            self.limit[col] = float(np.nanmax(shares)) * 2 + 0.001
        self.number_share = {c: float(self._is_number(sample[c][sample[c].notna()]).mean()) for c in self.known}
        return self

    def detect(self, batch):
        flags, bad, shown = self._empty(batch), [], ""
        for col, known in self.known.items():
            if col not in batch.columns:
                continue
            values = text(batch, col)
            present = values.notna().to_numpy()
            unknown = present & ~values.fillna("").map(mask_of).isin(known).to_numpy()
            share = unknown.sum() / max(present.sum(), 1)
            numbers = self._is_number(batch[col])
            number_share = numbers[present].mean() if present.any() else 0.0
            drift = abs(number_share - self.number_share[col])
            if share > self.limit[col] or drift > 0.0005:
                wrong_type = present & (numbers != (self.number_share[col] > 0.5))
                flags |= (unknown if share > self.limit[col] else self._empty(batch)) | wrong_type
                bad.append(col)
                shown += f"{col}: {share:.1%} unseen value shapes, numeric share {number_share:.1%} vs {self.number_share[col]:.1%}, e.g. {values[wrong_type | unknown].head(1).tolist()}; "
        return self._result(batch, flags, bad, shown, "the shape share seen in the reference", "Value shapes drifted away from the reference", alert=bool(bad))


class DateMaskStat(Detector):
    problem, family = "date_format_switch", "stats"
    RARE = 0.0005

    def fit(self, reference):
        sample = sample_reference(reference, 100000)
        self.known = {}
        for col in DATE_COLUMNS:
            shapes = text(sample, col).dropna().map(mask_of).value_counts(normalize=True)
            self.known[col] = set(shapes[shapes >= self.RARE].index)
        return self

    def detect(self, batch):
        flags, bad, shown = self._empty(batch), [], ""
        for col, known in self.known.items():
            if col not in batch.columns:
                continue
            values = text(batch, col)
            unknown = values.notna().to_numpy() & ~values.fillna("").map(mask_of).isin(known).to_numpy()
            if unknown.any():
                flags |= unknown
                bad.append(col)
                shown += f"{col}: {unknown.mean():.1%} unseen shape from row {int(np.flatnonzero(unknown)[0])}; "
        return self._result(batch, flags, bad, shown, "date shapes seen in the reference", "The date's character shape changed partway through the batch")


class CoordinateZStat(Detector):
    """Robust z-score on each coordinate. An IsolationForest was tried first and scored 0% here: see RESULTS_B.md."""

    problem, family = "lat_lon_swap", "stats"
    MARGIN = 1.5

    def _z(self, frame):
        lat, lon = number(frame, "latitude"), number(frame, "longitude")
        return np.maximum(np.abs(lat - self.lat_median) / self.lat_mad, np.abs(lon - self.lon_median) / self.lon_mad), lat, lon

    def fit(self, reference):
        sample = sample_reference(reference, 100000)
        lat, lon = number(sample, "latitude").dropna(), number(sample, "longitude").dropna()
        self.lat_median, self.lon_median = float(lat.median()), float(lon.median())
        self.lat_mad, self.lon_mad = float((lat - self.lat_median).abs().median()), float((lon - self.lon_median).abs().median())
        self.threshold = float(np.nanmax(self._z(sample)[0])) * self.MARGIN
        return self

    def detect(self, batch):
        z, lat, lon = self._z(batch)
        flags = np.nan_to_num(z.to_numpy(), nan=0.0) > self.threshold
        return self._result(batch, flags, ["latitude", "longitude"], f"{int(flags.sum())} outlying points, e.g. {lat[flags].head(1).tolist()},{lon[flags].head(1).tolist()}", f"robust z at or below {self.threshold:.1f}", "A coordinate is far outside the distribution seen in the reference")


class DuplicateRateStat(Detector):
    problem, family = "exact_duplicates", "stats"
    Z = 4.0

    def _dups(self, frame):
        return frame.astype(str).duplicated(keep="first").to_numpy()

    def fit(self, reference):
        rates = [self._dups(c).mean() for c in chunks(sample_reference(reference, 100000), 5000, 15)]
        self.mean, self.std = float(np.mean(rates)), max(float(np.std(rates)), 1e-4)
        return self

    def detect(self, batch):
        dups = self._dups(batch)
        z = (dups.mean() - self.mean) / self.std
        fired = z > self.Z
        return self._result(batch, dups if fired else self._empty(batch), ["all columns"], f"duplicate rate {dups.mean():.2%}, z={z:.1f}", f"rate near {self.mean:.3%}", "Duplicate rate is abnormally high for a batch", alert=fired)


class NearDuplicateTextStat(Detector):
    """Character n-gram similarity between requests blocked by ZIP and complaint type, close together in time."""

    problem, family = "near_duplicates", "stats"
    WINDOW_MINUTES = 15
    SIM = 0.92

    def fit(self, reference):
        sample = sample_reference(reference, 30000)
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), max_features=30000, lowercase=True).fit(self._docs(sample))
        return self

    def _docs(self, frame):
        return (text(frame, "incident_address").fillna("") + " " + text(frame, "descriptor").fillna("") + " " + text(frame, "resolution_description").fillna("").str[:120]).tolist()

    def detect(self, batch):
        flags = self._empty(batch)
        created = when(batch, "created_date").to_numpy()
        zips, types = text(batch, "incident_zip").fillna("?").to_numpy(), text(batch, "complaint_type").fillna("?").to_numpy()
        keys = text(batch, "unique_key").fillna("").to_numpy()
        matrix = self.vectorizer.transform(self._docs(batch))
        groups: dict = {}
        for i, block in enumerate(zip(zips, types)):
            groups.setdefault(block, []).append(i)
        window = np.timedelta64(self.WINDOW_MINUTES, "m")
        for members in groups.values():
            if not 2 <= len(members) <= 400:
                continue
            idx = np.array(members)
            sims = (matrix[idx] @ matrix[idx].T).toarray()
            for a in range(len(idx)):
                for b in np.flatnonzero(sims[a, a + 1 :] >= self.SIM) + a + 1:
                    i, j = idx[a], idx[b]
                    if keys[i] != keys[j] and not np.isnat(created[i]) and not np.isnat(created[j]) and abs(created[i] - created[j]) <= window:
                        flags[i] = flags[j] = True
        return self._result(batch, flags, ["incident_address", "descriptor", "resolution_description", "created_date"], f"{int(flags.sum())} rows", f"no text similarity at or above {self.SIM} within {self.WINDOW_MINUTES} minutes", "Text nearly identical to a nearby request under another key")


class NullSpikeStat(Detector):
    """Binomial z-test per agency and column with a Bonferroni-style cut, floored by chunk-to-chunk variation."""

    problem, family = "null_spike", "stats"
    MIN_ROWS = 100
    Z = 6.0
    MIN_EFFECT = 0.10

    def fit(self, reference):
        sample = sample_reference(reference, 150000)
        self.columns = [c for c in sample.columns if c not in ("agency", "agency_name", "unique_key", "created_date", "closed_date", "resolution_action_updated_date")]
        rates = [c[self.columns].isna().groupby(c["agency"].to_numpy()).mean() for c in chunks(sample, 5000, 25)]
        stack = pd.concat(rates)
        self.mean = stack.groupby(level=0).mean()
        self.std = stack.groupby(level=0).std().fillna(0)
        return self

    def detect(self, batch):
        flags, findings, cols = self._empty(batch), [], []
        if "agency" not in batch.columns:
            return self._result(batch, flags, [], "", "", "", alert=False)
        for name, idx in batch.groupby("agency", sort=False).indices.items():
            if len(idx) < self.MIN_ROWS or name not in self.mean.index:
                continue
            for col in self.columns:
                if col not in batch.columns:
                    continue
                nulls = batch[col].iloc[idx].isna().to_numpy()
                p = float(self.mean.at[name, col])
                sd = max(np.sqrt(max(p * (1 - p), 1e-4) / len(idx)), float(self.std.at[name, col]))
                z = (nulls.mean() - p) / sd
                if z > self.Z and nulls.mean() - p > self.MIN_EFFECT:
                    findings.append(f"{name}.{col}: {nulls.mean():.0%} vs {p:.0%} (z={z:.1f})")
                    cols.append(col)
                    flags[idx] |= nulls
        return self._result(batch, flags, sorted(set(cols)), "; ".join(findings[:5]), "null rate near the agency's baseline", "An agency's null rate is significantly above its baseline", alert=bool(findings))


class DurationOutlierStat(Detector):
    problem, family = "closed_before_created", "stats"
    QUANTILE = 0.001

    def _signed(self, frame):
        seconds = (when(frame, "closed_date") - when(frame, "created_date")).dt.total_seconds()
        return np.sign(seconds) * np.log1p(np.abs(seconds))

    def fit(self, reference):
        sample = sample_reference(reference, 200000)
        frame = pd.DataFrame({"t": text(sample, "complaint_type"), "d": self._signed(sample)}).dropna()
        self.floor = frame.groupby("t")["d"].quantile(self.QUANTILE).to_dict()
        self.default = float(frame["d"].quantile(self.QUANTILE))
        return self

    def detect(self, batch):
        duration = self._signed(batch)
        floors = text(batch, "complaint_type").map(self.floor).fillna(self.default).astype(float)
        flags = (duration < floors).to_numpy()
        return self._result(batch, flags, ["created_date", "closed_date"], f"{int(flags.sum())} rows with unusually short or negative durations", "duration above its complaint type's 0.1% tail", "Close time is an outlier for this complaint type")


class ZipBoroughStat(Detector):
    problem, family = "zip_borough_mismatch", "stats"
    MIN_P = 0.005
    QUANTILE = 0.999

    def fit(self, reference):
        sample = sample_reference(reference, 200000)
        pairs = pd.DataFrame({"z": text(sample, "incident_zip"), "b": text(sample, "borough"), "lat": number(sample, "latitude"), "lon": number(sample, "longitude")})
        known = pairs.dropna(subset=["z", "b"])
        known = known[known["b"] != "Unspecified"]
        self.prob = known.groupby("z")["b"].value_counts(normalize=True).to_dict()
        geo = pairs.dropna(subset=["z", "lat", "lon"])
        self.centroid = geo.groupby("z")[["lat", "lon"]].median()
        dist = self._km(geo["z"], geo["lat"], geo["lon"])
        self.max_km = float(np.nanquantile(dist, self.QUANTILE))
        return self

    def _km(self, zips, lat, lon):
        c = self.centroid.reindex(zips.to_numpy())
        return np.hypot((lat.to_numpy() - c["lat"].to_numpy()) * 111.0, (lon.to_numpy() - c["lon"].to_numpy()) * 84.0)

    def detect(self, batch):
        zips, boroughs = text(batch, "incident_zip"), text(batch, "borough")
        known_zip = zips.isin(self.centroid.index).to_numpy()
        prob = np.array([self.prob.get((z, b), 0.0) for z, b in zip(zips, boroughs)])
        unlikely = known_zip & boroughs.notna().to_numpy() & (boroughs != "Unspecified").to_numpy() & (prob < self.MIN_P)
        dist = self._km(zips, number(batch, "latitude"), number(batch, "longitude"))
        far = np.nan_to_num(dist, nan=0.0) > self.max_km
        flags = unlikely | far
        return self._result(batch, flags, ["incident_zip", "borough", "latitude", "longitude"], f"{int(unlikely.sum())} with P(borough|zip)<{self.MIN_P}, {int(far.sum())} over {self.max_km:.1f} km from the ZIP centre", "a likely borough, near the ZIP centre", "ZIP is statistically inconsistent with the borough or location")


class ComplaintDescriptorStat(Detector):
    problem, family = "complaint_descriptor_mismatch", "stats"
    MIN_COND = 0.001
    MIN_MODEL = 0.02

    def fit(self, reference):
        sample = sample_reference(reference, 200000)
        pairs = pd.DataFrame({"t": text(sample, "complaint_type"), "d": text(sample, "descriptor")}).dropna()
        self.cond = pairs.groupby("t")["d"].value_counts(normalize=True).to_dict()
        counts = pairs.value_counts().reset_index(name="n")
        counts = counts[counts["t"].map(counts["t"].value_counts()) >= 1]
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True, max_features=20000)
        features = self.vectorizer.fit_transform(counts["d"])
        self.model = SGDClassifier(loss="log_loss", alpha=1e-5, max_iter=25, random_state=0).fit(features, counts["t"], sample_weight=np.log1p(counts["n"]))
        self.index = {c: i for i, c in enumerate(self.model.classes_)}
        return self

    def detect(self, batch):
        types, descs = text(batch, "complaint_type"), text(batch, "descriptor")
        flags = self._empty(batch)
        present = (types.notna() & descs.notna()).to_numpy()
        if present.any():
            positions = np.flatnonzero(present)
            cond = np.array([self.cond.get((t, d), 0.0) for t, d in zip(types.iloc[positions], descs.iloc[positions])])
            proba = self.model.predict_proba(self.vectorizer.transform(descs.iloc[positions]))
            model_p = np.array([proba[r, self.index[t]] if t in self.index else 0.0 for r, t in enumerate(types.iloc[positions])])
            flags[positions] = (cond < self.MIN_COND) & (model_p < self.MIN_MODEL)
        return self._result(batch, flags, ["complaint_type", "descriptor"], f"{int(flags.sum())} rows, e.g. {types[flags].head(1).tolist()} with {descs[flags].head(1).tolist()}", f"P(descriptor|type)>={self.MIN_COND} or model P(type|text)>={self.MIN_MODEL}", "Descriptor is unlikely for this complaint type")


class ResolutionStatusStat(Detector):
    problem, family = "resolution_status_contradiction", "stats"
    QUANTILE = 0.0005

    def fit(self, reference):
        sample = sample_reference(reference, 60000)
        frame = pd.DataFrame({"s": text(sample, "status"), "r": text(sample, "resolution_description")}).dropna()
        frame = frame[frame["s"] != "Unspecified"]
        frame["closed"] = frame["s"] == "Closed"
        counts = frame.value_counts(["r", "closed"]).reset_index(name="n")
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=40000, lowercase=True, sublinear_tf=True)
        features = self.vectorizer.fit_transform(counts["r"])
        self.model = LogisticRegression(max_iter=300, C=4.0, class_weight="balanced").fit(features, counts["closed"], sample_weight=np.log1p(counts["n"]))
        probe = frame.sample(min(10000, len(frame)), random_state=3)
        scores = self._agree(probe["r"], probe["closed"].to_numpy())
        self.threshold = float(np.quantile(scores, self.QUANTILE))
        return self

    def _agree(self, texts, closed):
        p_closed = self.model.predict_proba(self.vectorizer.transform(texts))[:, list(self.model.classes_).index(True)]
        return np.where(closed, p_closed, 1 - p_closed)

    def detect(self, batch):
        status, res = text(batch, "status"), text(batch, "resolution_description")
        flags = self._empty(batch)
        present = (status.notna() & res.notna() & (status != "Unspecified")).to_numpy()
        if present.any():
            positions = np.flatnonzero(present)
            flags[positions] = self._agree(res.iloc[positions], (status.iloc[positions] == "Closed").to_numpy()) < self.threshold
        return self._result(batch, flags, ["status", "resolution_description"], f"{int(flags.sum())} rows, e.g. status {status[flags].head(1).tolist()}", f"model agreement with the status above {self.threshold:.3f}", "A text model says this resolution rarely goes with this status")


class PiiRarityStat(Detector):
    """Tokens and shapes never seen in years of templated resolution text are a personal-data signal."""

    problem, family = "pii_in_text", "stats"
    COLUMNS = ("descriptor", "resolution_description")
    QUANTILE = 0.9995

    def _score(self, values: pd.Series) -> np.ndarray:
        out = np.zeros(len(values))
        for i, value in enumerate(values):
            if not value:
                continue
            rare_caps = sum(1 for t in TOKEN_RE.findall(value) if t[0].isupper() and t.lower() not in self.vocab)
            digit_run = 3 if any(m not in self.known_contacts for m in CONTACT_RE.findall(value)) else 0
            out[i] = rare_caps + digit_run
        return out

    def fit(self, reference):
        sample = sample_reference(reference, 120000)
        counts: Counter = Counter()
        contacts: Counter = Counter()
        for col in self.COLUMNS:
            for value, n in text(sample, col).dropna().value_counts().items():
                for token in set(TOKEN_RE.findall(value)):
                    counts[token.lower()] += n
                for contact in set(CONTACT_RE.findall(value)):
                    contacts[contact] += n
        self.vocab = {t for t, n in counts.items() if n >= 3}
        self.known_contacts = {c for c, n in contacts.items() if n >= 5}  # agency help lines and mailboxes
        probe = sample.sample(min(20000, len(sample)), random_state=5)
        scores = np.maximum.reduce([self._score(text(probe, c).fillna("")) for c in self.COLUMNS])
        self.threshold = max(float(np.quantile(scores, self.QUANTILE)), 1.0)
        return self

    def detect(self, batch):
        scores = np.maximum.reduce([self._score(text(batch, c).fillna("")) for c in self.COLUMNS])
        flags = scores > self.threshold
        return self._result(batch, flags, list(self.COLUMNS), f"{int(flags.sum())} rows, max rarity score {scores.max() if len(scores) else 0:.0f} (value withheld from the alert)", f"rarity score at or below {self.threshold:.0f}", "Text holds capitalised words or number shapes unseen in the reference")


ALL = [FingerprintStat, TypeShareStat, DateMaskStat, CoordinateZStat, DuplicateRateStat, NearDuplicateTextStat, NullSpikeStat, DurationOutlierStat, ZipBoroughStat, ComplaintDescriptorStat, ResolutionStatusStat, PiiRarityStat]
