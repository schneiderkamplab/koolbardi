from pathlib import Path

from koolbardi.config import load_config


def test_pilot_is_balanced_and_complexity_shares_sum_to_one():
    config = load_config(Path(__file__).parents[1] / "configs/dfm11-pilot.yaml")
    assert {lane.language: lane.accepted_target for lane in config.lanes} == {"da": 10_000, "en": 10_000}
    assert all(sum(lane.complexity_shares.values()) == 1 for lane in config.lanes)

