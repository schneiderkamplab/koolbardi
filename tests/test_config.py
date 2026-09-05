from pathlib import Path

from koolbardi.config import load_config


def test_pilot_is_balanced_and_complexity_shares_sum_to_one():
    config = load_config(Path(__file__).parents[1] / "configs/dfm11-pilot.yaml")
    assert {lane.language: lane.accepted_target for lane in config.lanes} == {"da": 10_000, "en": 10_000}
    assert all(sum(lane.complexity_shares.values()) == 1 for lane in config.lanes)


def test_a4b_pilot_has_exact_length_and_language_targets():
    config = load_config(Path(__file__).parents[1] / "configs/dfm11-pilot-10k-a4b.yaml")
    assert sum(lane.accepted_target for lane in config.lanes) == 10_000
    assert sum(band.share for band in config.length_bands.values()) == 1
    assert max(band.max_tokens for band in config.length_bands.values()) == 3968
    assert config.max_sequence_tokens == 4096


def test_final_selection_requires_valid_targets():
    config = load_config(Path(__file__).parents[1] / "configs/dfm11-million-controlled-a4b.yaml")
    assert config.final_selection.targets == {"da": 500_000, "en": 500_000}
    assert config.final_selection.audit_buffer == 1.07
    assert config.final_selection.retain_surplus is True
