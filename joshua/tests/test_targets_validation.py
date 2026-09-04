import pytest

from validation import ValidationError, validate_targets_payload


def test_targets_summing_to_100_are_accepted():
    payload = {
        "targets": [
            {"asset_class": "Australian equities", "target_percent": 40},
            {"asset_class": "Crypto", "target_percent": 60},
        ],
    }

    targets = validate_targets_payload(payload)

    assert sum(t["target_percent"] for t in targets) == pytest.approx(100.0)


def test_targets_not_summing_to_100_are_rejected():
    payload = {
        "targets": [
            {"asset_class": "Australian equities", "target_percent": 40},
            {"asset_class": "Crypto", "target_percent": 50},
        ],
    }

    with pytest.raises(ValidationError) as exc_info:
        validate_targets_payload(payload)

    assert any("sum to 100" in message for message in exc_info.value.errors)


def test_seed_data_allocation_targets_sum_to_100():
    payload = {
        "targets": [
            {"asset_class": "Australian equities", "target_percent": 20},
            {"asset_class": "International equities", "target_percent": 15},
            {"asset_class": "ETFs", "target_percent": 15},
            {"asset_class": "REITs", "target_percent": 10},
            {"asset_class": "Government bonds", "target_percent": 10},
            {"asset_class": "Corporate bonds", "target_percent": 5},
            {"asset_class": "Cash", "target_percent": 5},
            {"asset_class": "Term deposits", "target_percent": 5},
            {"asset_class": "Commodities", "target_percent": 5},
            {"asset_class": "Crypto", "target_percent": 10},
        ],
    }

    targets = validate_targets_payload(payload)

    assert len(targets) == 10
    assert sum(t["target_percent"] for t in targets) == pytest.approx(100.0)
