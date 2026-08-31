from koolbardi.io import atomic_write_jsonl, read_jsonl


def test_atomic_jsonl(tmp_path):
    output = tmp_path / "nested" / "rows.jsonl"
    assert atomic_write_jsonl(output, [{"id": 1}, {"id": 2}]) == 2
    assert list(read_jsonl(output)) == [{"id": 1}, {"id": 2}]
    assert not list(output.parent.glob("*.tmp"))

