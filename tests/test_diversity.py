import json
import sqlite3
from pathlib import Path

from koolbardi.diversity import DiversityAssigner, diversity_condition


CATALOG = Path(__file__).parents[1] / "catalogs/topic-mode-v1.yaml"


def persona_store(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE personas (language TEXT, position INTEGER, source_id TEXT, payload TEXT, "
            "PRIMARY KEY(language, position)) WITHOUT ROWID"
        )
        for language in ("da", "en"):
            for position in range(7):
                payload = {"source": f"source-{language}", "occupation": f"job-{position}"}
                connection.execute(
                    "INSERT INTO personas VALUES (?, ?, ?, ?)",
                    (language, position, f"id-{position}", json.dumps(payload)),
                )


def test_catalog_balances_topics_and_modes(tmp_path):
    store = tmp_path / "personas.sqlite3"
    persona_store(store)
    assigner = DiversityAssigner(str(CATALOG), str(store), "en", 17)
    topic_count = len(assigner.topics)
    mode_count = len(assigner.modes)
    first_cycle = [assigner.assignment(index) for index in range(topic_count)]
    assert len({item.topic["id"] for item in first_cycle}) == topic_count == 136
    fixed_topic = [
        assigner.assignment(index * topic_count).mode["id"]
        for index in range(mode_count)
    ]
    assert len(set(fixed_topic)) == mode_count == 20
    assert len({assigner.assignment(index).persona["source_id"] for index in range(7)}) == 7
    assigner.close()


def test_embedded_input_mode_requires_material_in_request(tmp_path):
    store = tmp_path / "personas.sqlite3"
    persona_store(store)
    assigner = DiversityAssigner(str(CATALOG), str(store), "en", 3)
    assignment = next(
        assigner.assignment(index)
        for index in range(1000)
        if assigner.assignment(index).mode.get("embedded_input")
    )
    assert "must include the text or data" in diversity_condition("en", assignment)
    assigner.close()
