"""The evaluation files stay consistent with the taxonomy, so a bad edit fails here and not in a paid run."""

import csv
import sys
from pathlib import Path

import pytest

import taxonomy

EVAL = Path(__file__).parent.parent / "eval"
sys.path.insert(0, str(EVAL))


def rows(name):
    with open(EVAL / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("name", ["hard_cases.csv", "heldout_cases.csv"])
def test_expected_codes_exist_in_the_taxonomy(name):
    for r in rows(name):
        assert r["expected"] in taxonomy.REASONS, r["id"]
        assert not r["expected_secondary"] or r["expected_secondary"] in taxonomy.REASONS, r["id"]
        assert r["text"].strip(), r["id"]


def test_heldout_ids_are_unique_and_texts_do_not_repeat_other_sets():
    held = rows("heldout_cases.csv")
    assert len({r["id"] for r in held}) == len(held)
    seen = {r["text"] for r in rows("hard_cases.csv")}
    seen |= {r["roman_hinglish"] for r in rows("labelled_samples.csv")}
    seen |= {text for text, _, _ in taxonomy.EXAMPLES}
    assert not [r["id"] for r in held if r["text"] in seen]
    assert len({r["text"] for r in held}) == len(held)


def test_heldout_covers_most_of_the_list_and_the_eval_set_reaches_200():
    held = rows("heldout_cases.csv")
    covered = {r["expected"] for r in held}
    assert len(covered) >= 55, sorted(set(taxonomy.REASONS) - covered)
    assert len(rows("labelled_samples.csv")) + len(rows("hard_cases.csv")) + len(held) >= 200


def test_run_eval_loads_all_three_sets():
    import run_eval
    loaded = run_eval.load_rows("roman")
    assert {r["set"] for r in loaded} == {"labelled", "hard", "heldout"}
    assert len(loaded) >= 200
