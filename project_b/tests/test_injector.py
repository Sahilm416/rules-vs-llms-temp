"""Injector behaviour on a small synthetic batch, so these tests need no downloaded data."""
import numpy as np
import pandas as pd
import pytest

from project_b.injector import BATCH_LEVEL, PROBLEMS, inject

N = 400
RATE = 0.05


@pytest.fixture
def batch():
    rng = np.random.default_rng(1)
    boroughs = {"BROOKLYN": ["11201", "11215"], "QUEENS": ["11101", "11354"], "BRONX": ["10451", "10458"], "MANHATTAN": ["10001", "10025"]}
    types = {"Noise - Residential": ["Loud Music/Party", "Banging/Pounding"], "Noise - Street/Sidewalk": ["Loud Talking"], "Rodent": ["Rat Sighting"], "Illegal Parking": ["Blocked Hydrant"]}
    borough = rng.choice(list(boroughs), N)
    complaint = rng.choice(list(types), N)
    created = pd.date_range("2023-10-01", periods=N, freq="7min")
    return pd.DataFrame(
        {
            "unique_key": np.arange(1000, 1000 + N, dtype="int64"),
            "created_date": created.strftime("%Y-%m-%dT%H:%M:%S.000"),
            "closed_date": (created + pd.Timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.000"),
            "agency": rng.choice(["NYPD", "HPD", "DSNY"], N),
            "complaint_type": complaint,
            "descriptor": [str(rng.choice(types[c])) for c in complaint],
            "status": "Closed",
            "resolution_description": rng.choice(["The Police Department responded and took action.", "The condition was corrected."], N),
            "incident_zip": [str(rng.choice(boroughs[b])) for b in borough],
            "incident_address": [f"{i} MAIN STREET" for i in range(N)],
            "street_name": "MAIN STREET",
            "location_type": "Street",
            "community_board": "01 BROOKLYN",
            "borough": borough,
            "latitude": rng.uniform(40.5, 40.9, N),
            "longitude": rng.uniform(-74.2, -73.7, N),
        }
    )


@pytest.mark.parametrize("problem", PROBLEMS)
def test_contract(batch, problem):
    before = batch.copy(deep=True)
    result = inject(batch, problem, RATE, seed=7)
    pd.testing.assert_frame_equal(batch, before)
    assert len(result.row_labels) == len(result.batch)
    assert result.row_labels.dtype == bool and result.row_labels.any()
    assert result.batch_level == (problem in BATCH_LEVEL)


@pytest.mark.parametrize("problem", PROBLEMS)
def test_deterministic_for_a_seed(batch, problem):
    first, second = inject(batch, problem, RATE, seed=3), inject(batch, problem, RATE, seed=3)
    pd.testing.assert_frame_equal(first.batch, second.batch)
    assert np.array_equal(first.row_labels, second.row_labels)
    assert first.meta == second.meta


@pytest.mark.parametrize("problem", [p for p in PROBLEMS if p not in ("renamed_dropped_column", "date_format_switch")])
def test_rate_is_controlled(batch, problem):
    count = int(inject(batch, problem, RATE, seed=5).row_labels.sum())
    assert 1 <= count <= round(RATE * N)


def test_rename_or_drop_changes_schema(batch):
    seen = set()
    for seed in range(12):
        result = inject(batch, "renamed_dropped_column", RATE, seed)
        seen.add(result.meta["variant"])
        assert result.meta["column"] not in result.batch.columns
    assert seen == {"renamed", "dropped"}


def test_type_change_mixes_types(batch):
    for seed in range(8):
        result = inject(batch, "type_change", RATE, seed)
        column = result.meta["columns"][0]
        kinds = {type(v) for v in result.batch[column]}
        assert len(kinds) > 1, result.meta["variant"]


def test_date_switch_starts_partway(batch):
    result = inject(batch, "date_format_switch", RATE, seed=1)
    start = result.meta["start_row"]
    assert 0 < start < N
    iso = result.batch["created_date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}T.*")
    assert iso.iloc[:start].all() and not iso.iloc[start:].any()
    assert result.row_labels[start:].all() and not result.row_labels[:start].any()


def test_lat_lon_swap_swaps_only_labelled(batch):
    result = inject(batch, "lat_lon_swap", RATE, seed=1)
    labels = result.row_labels
    assert (result.batch.loc[labels, "latitude"] < 0).all()
    assert (result.batch.loc[~labels, "latitude"] > 0).all()


def test_exact_duplicates_are_exact_copies(batch):
    result = inject(batch, "exact_duplicates", RATE, seed=1)
    assert len(result.batch) == N + int(result.row_labels.sum())
    copies = result.batch[result.row_labels]
    assert copies["unique_key"].isin(batch["unique_key"]).all()
    assert result.batch.duplicated(keep=False).sum() == 2 * len(copies)


def test_near_duplicates_get_new_keys_and_differ(batch):
    result = inject(batch, "near_duplicates", RATE, seed=1)
    copies = result.batch[result.row_labels]
    assert not copies["unique_key"].isin(batch["unique_key"]).any()
    assert result.batch["unique_key"].is_unique
    merged = copies.drop(columns="unique_key").merge(batch.drop(columns="unique_key"), how="inner")
    assert merged.empty, "every near-duplicate must differ from every original"


def test_null_spike_hits_one_agency(batch):
    result = inject(batch, "null_spike", 0.1, seed=2)
    assert result.batch.loc[result.row_labels, "agency"].nunique() == 1
    assert result.batch.loc[result.row_labels, result.meta["column"]].isna().all()


def test_closed_before_created(batch):
    result = inject(batch, "closed_before_created", RATE, seed=1)
    out = result.batch
    assert (out.loc[result.row_labels, "closed_date"] < out.loc[result.row_labels, "created_date"]).all()
    assert (out.loc[~result.row_labels, "closed_date"] >= out.loc[~result.row_labels, "created_date"]).all()


def test_zip_comes_from_another_borough(batch):
    result = inject(batch, "zip_borough_mismatch", RATE, seed=1, reference=batch)
    valid = batch.groupby("borough")["incident_zip"].agg(set).to_dict()
    for _, row in result.batch[result.row_labels].iterrows():
        assert row["incident_zip"] not in valid[row["borough"]]
        assert any(row["incident_zip"] in codes for codes in valid.values())


def test_descriptor_pairs_were_never_seen(batch):
    result = inject(batch, "complaint_descriptor_mismatch", 0.2, seed=1, reference=batch)
    seen = set(zip(batch["complaint_type"], batch["descriptor"]))
    pairs = zip(result.batch.loc[result.row_labels, "complaint_type"], result.batch.loc[result.row_labels, "descriptor"])
    assert not (set(pairs) & seen)
    assert {"never_cooccurring", "sibling", "novel"} >= set(result.meta["variant_counts"])
    assert len(result.meta["variant_counts"]) >= 2


def test_contradiction_keeps_closed_date_consistent_with_status(batch):
    result = inject(batch, "resolution_status_contradiction", 0.2, seed=1)
    out = result.batch
    assert out.loc[out["status"] == "Closed", "closed_date"].notna().all()
    assert out.loc[out["status"] != "Closed", "closed_date"].isna().all()
    assert len(result.meta["variant_counts"]) == 3


def test_pii_is_synthetic_and_covers_bare_names(batch):
    result = inject(batch, "pii_in_text", 0.2, seed=1)
    assert "name_bare" in result.meta["variant_counts"]
    text = " ".join(result.batch.loc[result.row_labels, "resolution_description"])
    assert "555-0" in text or "555.0" in text
    assert "@example." in text


def test_variant_list_aligns_with_labels(batch):
    result = inject(batch, "near_duplicates", RATE, seed=4)
    variants = result.meta["row_variant"]
    assert [v is not None for v in variants] == list(result.row_labels)
