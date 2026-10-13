"""The human checks: sampling wrongful ejections for coding, kappa, and annotation agreement."""

import asyncio
import csv

import pytest

from amongagents.agent.llm import LLMConfig
from govlab.cli import main
from govlab.design import ExperimentSpec
from govlab.metrics import game_row
from govlab.qual import (
    ANNOTATED_FIELDS,
    agreement,
    annotation_template,
    cohens_kappa,
    export_sample,
    kappa_from_sheets,
    sample_meetings,
    transcript,
    wrongful_meetings,
)
from govlab.runner import Runner
from govlab.store import RunStore


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    spec = ExperimentSpec(
        name="qual", games_per_condition=8, concurrency=8, llm=LLMConfig(provider="mock")
    )
    run = RunStore.create(spec, tmp_path_factory.mktemp("runs"))
    Runner.retry_delay = 0.0
    asyncio.run(Runner(run).run())
    return run


def test_every_sampled_meeting_ejected_a_crewmate(store):
    everything = wrongful_meetings(store)
    assert len(everything) > 4
    for meeting in everything:
        tallies = [e for e in store.events(meeting["game_id"]) if e["type"] == "tally"]
        assert tallies[meeting["meeting"] - 1]["ejected_identity"] == "Crewmate"


def test_the_sample_is_spread_over_conditions_and_reproducible(store):
    sample = sample_meetings(store, n=8, seed=1)
    assert sample == sample_meetings(store, n=8, seed=1)
    assert len(sample) == 8 and len({(m["game_id"], m["meeting"]) for m in sample}) == 8
    per_condition = {}
    for m in sample:
        per_condition[m["condition"]] = per_condition.get(m["condition"], 0) + 1
    available = {m["condition"] for m in wrongful_meetings(store)}
    assert set(per_condition) == available  # no condition with material is left out
    assert sample_meetings(store, n=10_000) and len(sample_meetings(store, n=10_000)) == len(
        wrongful_meetings(store)
    )


def test_a_transcript_reads_as_the_meeting(store):
    meeting = wrongful_meetings(store)[0]
    text = transcript(store, meeting["game_id"], meeting["engine_meeting"])
    assert "Insider: Player" in text and "**Round 1**" in text and "(final)" in text
    assert "votes **" in text and "ejected, a Crewmate" in text


def test_export_writes_transcripts_and_a_blank_coding_sheet(store):
    out = export_sample(store, n=5, seed=0)
    assert (out / "meetings.md").read_text().count("## Item") == 5
    rows = list(csv.DictReader((out / "coding_sheet.csv").open()))
    assert [r["item"] for r in rows] == ["1", "2", "3", "4", "5"]
    assert all(r["code"] == "" for r in rows)


def test_cohens_kappa_on_known_values():
    assert cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohens_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    # 2x2 table [[20, 5], [10, 15]]: observed 0.70, expected 0.50 -> kappa 0.40
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert cohens_kappa(a, b) == pytest.approx(0.4)
    assert cohens_kappa(["a", "a"], ["a", "a"]) is None  # no variation: undefined
    with pytest.raises(ValueError):
        cohens_kappa(["a"], ["a", "b"])


def test_kappa_from_two_authors_sheets(tmp_path):
    def sheet(name, codes):
        path = tmp_path / name
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["item", "code"])
            writer.writerows([[i + 1, c] for i, c in enumerate(codes)])
        return path

    a, b = (
        sheet("a.csv", ["bandwagon", "bandwagon", "framed", "framed"]),
        sheet("b.csv", ["bandwagon", "bandwagon", "framed", "bandwagon"]),
    )
    result = kappa_from_sheets(a, b)
    assert result["items"] == 4 and result["agreement"] == 0.75 and result["disagreements"] == ["4"]
    assert result["kappa"] == pytest.approx(0.5)
    with pytest.raises(ValueError, match="not yet coded"):
        kappa_from_sheets(a, sheet("c.csv", ["bandwagon", "", "framed", "framed"]))


def test_annotation_agreement_is_perfect_for_correct_annotations_and_counts_errors(store, tmp_path):
    template = annotation_template(store, n=10, seed=0)
    rows = list(csv.DictReader(template.open()))
    assert len(rows) == 10 and all(r[f] == "" for r in rows for f in ANNOTATED_FIELDS)

    for row in rows:  # a careful annotator
        computed = game_row(store.events(row["game_id"]))
        row.update({f: "" if computed[f] is None else str(computed[f]) for f in ANNOTATED_FIELDS})
    correct = tmp_path / "correct.csv"
    with correct.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    result = agreement(store, correct)
    assert (result["fields"], result["rate"], result["mismatches"]) == (60, 1.0, [])

    rows[0]["kills"] = str(int(rows[0]["kills"]) + 1)  # one slip
    rows[1]["winner"] = "crew" if rows[1]["winner"] == "impostor" else "impostor"
    wrong = tmp_path / "wrong.csv"
    with wrong.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    result = agreement(store, wrong)
    assert result["agreed"] == 58 and {m["field"] for m in result["mismatches"]} == {
        "kills",
        "winner",
    }
    assert main(["validate", str(store.path), str(correct)]) == 0
    assert (
        main(["validate", str(store.path), str(wrong)]) == 0
    )  # 58/60 = 96.7% still clears the 95% gate
