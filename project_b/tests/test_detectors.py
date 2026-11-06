"""Fast checks on hand-built frames. The measured numbers live in evaluate.py; these guard detector logic."""
import numpy as np
import pandas as pd
import pytest

from project_b.detectors import rules, stats
from project_b.detectors.base import mask_of, text
from project_b.evaluate import explain_score, wilson


def _frame(n=200):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "unique_key": np.arange(1, n + 1, dtype="int64"),
        "created_date": [f"2023-01-{1 + i % 27:02d}T10:00:{i % 60:02d}.000" for i in range(n)],
        "closed_date": [f"2023-02-{1 + i % 27:02d}T10:00:00.000" for i in range(n)],
        "agency": ["NYPD"] * n,
        "complaint_type": ["Noise"] * n,
        "descriptor": ["Loud Music"] * n,
        "incident_zip": ["11201"] * n,
        "borough": ["BROOKLYN"] * n,
        "status": ["Closed"] * n,
        "resolution_description": ["The Police Department responded to the complaint."] * n,
        "latitude": 40.7 + rng.random(n) / 100,
        "longitude": -73.9 - rng.random(n) / 100,
    })


def test_schema_rule_names_dropped_and_extra_columns():
    frame = _frame()
    det = rules.SchemaRule().fit(frame)
    result = det.detect(frame.rename(columns={"status": "state"}))
    assert result.batch_alert and {"status", "state"} <= set(result.alerts[0].columns)
    assert not det.detect(frame).batch_alert


def test_swapped_coordinates_are_flagged_only_where_swapped():
    frame = _frame()
    frame.loc[3, ["latitude", "longitude"]] = [-73.9, 40.7]
    flags = rules.CoordinateRule().fit(frame).detect(frame).row_flags
    assert flags[3] and flags.sum() == 1


def test_closed_before_created():
    frame = _frame()
    frame.loc[5, "closed_date"] = "2022-01-01T00:00:00.000"
    assert np.flatnonzero(rules.ClosedBeforeCreatedRule().fit(frame).detect(frame).row_flags).tolist() == [5]


def test_date_switch_rule_finds_the_new_format():
    frame = _frame()
    frame.loc[150:, "created_date"] = "01/05/2023 10:00:00 AM"
    assert rules.DateFormatRule().fit(frame).detect(frame).row_flags[150:].all()


def test_exact_duplicate_flags_only_the_copy():
    frame = pd.concat([_frame(), _frame().iloc[[7]]], ignore_index=True)
    flags = rules.ExactDuplicateRule().fit(frame).detect(frame).row_flags
    assert flags[-1] and flags.sum() == 1


def test_pii_rule_ignores_institutional_contact_but_catches_new_one():
    reference = _frame()
    reference["resolution_description"] = "Please call (212) 676-1600 for results."
    det = rules.PiiRule().fit(reference)
    batch = reference.head(2).copy()
    batch.loc[1, "resolution_description"] = "Call back 917-555-0123 for access."
    assert det.detect(batch).row_flags.tolist() == [False, True]


def test_detectors_survive_a_dropped_column():
    frame = _frame()
    for cls in (*rules.ALL, *stats.ALL):
        if cls in (stats.ResolutionStatusStat, stats.ComplaintDescriptorStat, stats.TypeShareStat, stats.NullSpikeStat, stats.NearDuplicateTextStat, stats.PiiRarityStat, stats.ZipBoroughStat, stats.DuplicateRateStat, stats.CoordinateZStat):
            continue  # these need realistic variety to fit; the full evaluation exercises them
        det = cls().fit(frame)
        det.detect(frame.drop(columns=["descriptor"]))


def test_helpers():
    assert mask_of("2023-01-05") == "dddd-dd-dd"
    assert text(pd.DataFrame({"a": [1]}), "missing").isna().all()
    low, high = wilson(9, 10)
    assert low < 0.9 < high and wilson(0, 0) == [None, None]
    assert explain_score([]) is None


@pytest.mark.parametrize("cls", [*rules.ALL, *stats.ALL])
def test_every_detector_declares_problem_and_family(cls):
    assert cls.problem and cls.family in ("rules", "stats")
