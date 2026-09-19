"""Tests for radar_scorecards and radar_entries against real JSON files —
same coverage gap as html_blog: exercised in test_pipeline.py only through
hand-built Document objects that skip the adapters' own JSON parsing."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.adapters.radar_entries import RadarEntriesAdapter
from corpusatlas.adapters.radar_scorecards import RadarScorecardsAdapter


def write_json(data) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        return f.name


SCORECARDS = {
    "assessments": {
        "olap": {
            "title": "OLAP",
            "url": "/architecture-radar/olap",
            "published": "2026-07-08",
            "use_case": "Sub-second aggregation at scale.",
            "platforms": {"ClickHouse": [4.1], "Snowflake": [3.8]},
            "target": "ClickHouse",
            "category": "analytics",
            "reviewed": "2026-07-08",
            "verdict": "Adopt ClickHouse for high-concurrency serving.",
        }
    }
}


def test_scorecards_yields_one_document_per_assessment():
    docs = list(RadarScorecardsAdapter(path=write_json(SCORECARDS)).documents())
    assert len(docs) == 1
    d = docs[0]
    assert d.id == "assessment:olap"
    assert d.title == "OLAP"
    assert d.kind == "assessment"
    assert d.date == "2026-07-08"
    assert d.meta["platforms"] == ["ClickHouse", "Snowflake"]
    assert d.meta["target"] == "ClickHouse"
    assert d.meta["verdict"].startswith("Adopt")


def test_scorecards_falls_back_to_slug_title_and_default_url_when_missing():
    minimal = {"assessments": {"bare": {"platforms": {}}}}
    docs = list(RadarScorecardsAdapter(path=write_json(minimal)).documents())
    assert docs[0].title == "bare"
    assert docs[0].url == "/architecture-radar/bare"


RADAR = {
    "edition": "2026-Q3",
    "entries": [
        {
            "id": "clickhouse", "name": "ClickHouse", "url": "/architecture-radar/olap",
            "quadrant": "platforms", "ring": "adopt", "category": "analytics", "reviewed": "2026-07-08",
            "scorecard": {"assessment": "olap", "options": ["ClickHouse"]},
            "history": [{"date": "2026-01-01", "event": "added", "ring": "trial"},
                       {"date": "2026-07-08", "event": "promoted", "ring": "adopt"}],
        },
        {
            "id": "eval-driven", "name": "Eval-driven development", "url": "/blog/eval-driven-development",
            "quadrant": "practices", "ring": "adopt",
            "history": [{"date": "2026-02-01", "event": "added", "ring": "adopt"}],
        },
    ],
}


def test_radar_entries_yields_one_document_per_entry_with_the_radar_prefix():
    docs = {d.id: d for d in RadarEntriesAdapter(path=write_json(RADAR)).documents()}
    assert set(docs) == {"radar:clickhouse", "radar:eval-driven"}
    assert docs["radar:clickhouse"].kind == "radar-entry"
    assert docs["radar:clickhouse"].title == "ClickHouse"


def test_radar_entries_takes_the_added_date_from_history_not_the_latest_event():
    docs = {d.id: d for d in RadarEntriesAdapter(path=write_json(RADAR)).documents()}
    # clickhouse's history has "added" at 2026-01-01 and "promoted" later —
    # the date field is when it was added, not the most recent ring change.
    assert docs["radar:clickhouse"].date == "2026-01-01"


def test_radar_entries_resolves_documented_in_through_doc_prefixes():
    docs = {d.id: d for d in RadarEntriesAdapter(path=write_json(RADAR)).documents()}
    # url "/architecture-radar/olap" -> "assessment:olap" via the default DOC_PREFIXES
    assert docs["radar:clickhouse"].meta["documented_in"] == "assessment:olap"
    # url "/blog/eval-driven-development" -> "eval-driven-development" (empty id_prefix)
    assert docs["radar:eval-driven"].meta["documented_in"] == "eval-driven-development"


def test_radar_entries_carries_the_scorecard_join_and_full_history():
    docs = {d.id: d for d in RadarEntriesAdapter(path=write_json(RADAR)).documents()}
    ch = docs["radar:clickhouse"]
    assert ch.meta["assessment"] == "olap"
    assert ch.meta["options"] == ["ClickHouse"]
    assert ch.meta["edition"] == "2026-Q3"
    assert len(ch.meta["history"]) == 2


def test_radar_entries_with_no_scorecard_join_still_works():
    docs = {d.id: d for d in RadarEntriesAdapter(path=write_json(RADAR)).documents()}
    practice = docs["radar:eval-driven"]
    assert practice.meta["assessment"] is None
    assert practice.meta["options"] == []


def test_custom_doc_prefixes_override_the_default_mapping():
    custom = RadarEntriesAdapter(path=write_json(RADAR), doc_prefixes={"/architecture-radar/": "call:"})
    docs = {d.id: d for d in custom.documents()}
    assert docs["radar:clickhouse"].meta["documented_in"] == "call:olap"
    # A url that doesn't match any configured prefix resolves to None, not a crash.
    assert docs["radar:eval-driven"].meta["documented_in"] is None
