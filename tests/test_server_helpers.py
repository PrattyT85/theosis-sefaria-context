import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from context_server import flatten_remote_text, metadata_dict  # noqa: E402


def test_flatten_remote_nested_text():
    assert flatten_remote_text([["one", "two"], ["three"]]) == "one\ntwo\nthree"


def test_metadata_dict_accepts_json_string():
    assert metadata_dict('{"license":"CC0"}') == {"license": "CC0"}
    assert metadata_dict("not-json") == {}
