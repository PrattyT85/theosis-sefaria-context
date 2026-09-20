import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from sefaria_import import flatten  # noqa: E402


def test_flatten_onkelos_cltk_path_to_ref():
    records = flatten({"0_Chapter, 0_Verse": "בראשית"}, "Onkelos Genesis")
    assert records == [("Onkelos Genesis 1:1", ("0_Chapter", "0_Verse"), "בראשית")]


def test_flatten_rejects_duplicate_refs():
    with pytest.raises(ValueError, match="Reference collision"):
        flatten({"0_Chapter, 0_Verse": "a", "0_Chapter, 0_Verse ": "b"}, "Onkelos Genesis")


def test_flatten_supports_historical_variable_depth():
    assert flatten({"1_Book, 6_Chapter, 10_Paragraph": "war"}, "The War of the Jews")[0][0] == "The War of the Jews 2:7:11"
    assert flatten({"1_Chapter, 0_Paragraph, 0_Section": "philo"}, "On Joseph")[0][0] == "On Joseph 2:1:1"
