import pytest

from allocation import build_portfolio_report, calculate_holding_metrics


def make_holding(**overrides):
    holding = {
        "id": 1,
        "user_id": 1,
        "ticker": "TEST",
        "asset_name": "Test Co",
        "asset_class": "Australian equities",
        "units": 10.0,
        "average_cost": 10.0,
        "currency": "AUD",
        "last_price": 12.0,
        "price_as_at": "2026-08-22",
        "purchase_date": "2024-01-01",
        "notes": None,
    }
    holding.update(overrides)
    return holding


def test_normal_portfolio_with_gains_and_losses():
    holdings = [
        make_holding(id=1, ticker="A", asset_class="Australian equities", units=100, average_cost=10, last_price=15),
        make_holding(id=2, ticker="B", asset_class="International equities", units=50, average_cost=20, last_price=18),
        make_holding(id=3, ticker="C", asset_class="Australian equities", units=20, average_cost=50, last_price=55),
    ]

    report = build_portfolio_report(holdings)
    by_id = {h["id"]: h for h in report["holdings"]}

    assert by_id[1]["market_value"] == pytest.approx(1500.0)
    assert by_id[1]["cost_basis"] == pytest.approx(1000.0)
    assert by_id[1]["gain_loss"] == pytest.approx(500.0)
    assert by_id[1]["gain_loss_percent"] == pytest.approx(50.0)

    assert by_id[2]["market_value"] == pytest.approx(900.0)
    assert by_id[2]["gain_loss"] == pytest.approx(-100.0)
    assert by_id[2]["gain_loss_percent"] == pytest.approx(-10.0)

    assert by_id[3]["gain_loss"] == pytest.approx(100.0)
    assert by_id[3]["gain_loss_percent"] == pytest.approx(10.0)

    portfolio = report["portfolio"]
    assert portfolio["total_market_value"] == pytest.approx(3500.0)
    assert portfolio["total_cost"] == pytest.approx(3000.0)
    assert portfolio["total_gain_loss"] == pytest.approx(500.0)

    allocation_by_class = {a["asset_class"]: a for a in portfolio["asset_class_allocation"]}
    assert allocation_by_class["Australian equities"]["market_value"] == pytest.approx(2600.0)
    # Unrounded fraction -- proves no premature rounding happened mid-calculation.
    assert allocation_by_class["Australian equities"]["percent_of_total"] == pytest.approx(2600 / 3500 * 100, rel=1e-9)
    assert allocation_by_class["International equities"]["market_value"] == pytest.approx(900.0)
    assert allocation_by_class["International equities"]["percent_of_total"] == pytest.approx(900 / 3500 * 100, rel=1e-9)

    total_percent = sum(a["percent_of_total"] for a in portfolio["asset_class_allocation"])
    assert total_percent == pytest.approx(100.0)


def test_holding_priced_below_average_cost_is_a_loss():
    holding = make_holding(units=10, average_cost=100, last_price=80)
    metrics = calculate_holding_metrics(holding)

    assert metrics["cost_basis"] == pytest.approx(1000.0)
    assert metrics["market_value"] == pytest.approx(800.0)
    assert metrics["gain_loss"] == pytest.approx(-200.0)
    assert metrics["gain_loss"] < 0
    assert metrics["gain_loss_percent"] == pytest.approx(-20.0)
    assert metrics["gain_loss_percent"] < 0


def test_empty_portfolio_has_no_division_by_zero():
    report = build_portfolio_report([])

    assert report["holdings"] == []
    assert report["portfolio"]["total_market_value"] == 0.0
    assert report["portfolio"]["total_cost"] == 0.0
    assert report["portfolio"]["total_gain_loss"] == 0.0
    assert report["portfolio"]["asset_class_allocation"] == []


def test_zero_value_portfolio_with_holdings_present_has_no_division_by_zero():
    """The percent_of_total guard is only reachable with holdings present.

    test_empty_portfolio_has_no_division_by_zero passes an empty list, which
    never enters the loop and so never reaches the division at all. This case
    does: the allocation list is non-empty but the total market value is zero.
    """
    holdings = [
        make_holding(id=1, asset_class="Cash", units=10, average_cost=5, last_price=0),
        make_holding(id=2, asset_class="Crypto", units=4, average_cost=25, last_price=0),
    ]

    report = build_portfolio_report(holdings)
    portfolio = report["portfolio"]

    assert portfolio["total_market_value"] == 0.0
    assert portfolio["total_cost"] == pytest.approx(150.0)
    assert portfolio["total_gain_loss"] == pytest.approx(-150.0)

    entries = portfolio["asset_class_allocation"]
    assert len(entries) == 2, "guard is only exercised when the loop produced entries"
    for entry in entries:
        assert entry["market_value"] == 0.0
        assert entry["percent_of_total"] == 0.0


def test_fractional_units_from_seed_data():
    """Seed data holds BTC at 0.25 units and ETH at 3.

    Fractional positions are the norm for crypto and unit trusts, so they
    belong in the covered path rather than being treated as an edge case.
    """
    btc = make_holding(id=1, ticker="BTC", asset_class="Crypto",
                       units=0.25, average_cost=45000.00, last_price=98000.00)
    eth = make_holding(id=2, ticker="ETH", asset_class="Crypto",
                       units=3, average_cost=2800.00, last_price=3400.00)

    report = build_portfolio_report([btc, eth])
    by_id = {h["id"]: h for h in report["holdings"]}

    assert by_id[1]["cost_basis"] == pytest.approx(11250.0)
    assert by_id[1]["market_value"] == pytest.approx(24500.0)
    assert by_id[1]["gain_loss"] == pytest.approx(13250.0)
    assert by_id[1]["gain_loss_percent"] == pytest.approx(13250 / 11250 * 100)

    assert by_id[2]["cost_basis"] == pytest.approx(8400.0)
    assert by_id[2]["market_value"] == pytest.approx(10200.0)
    assert by_id[2]["gain_loss"] == pytest.approx(1800.0)
    assert by_id[2]["gain_loss_percent"] == pytest.approx(1800 / 8400 * 100)

    portfolio = report["portfolio"]
    assert portfolio["total_market_value"] == pytest.approx(34700.0)
    assert portfolio["total_cost"] == pytest.approx(19650.0)
    assert portfolio["total_gain_loss"] == pytest.approx(15050.0)

    # Both holdings are Crypto, so the class aggregates to the whole portfolio.
    assert len(portfolio["asset_class_allocation"]) == 1
    assert portfolio["asset_class_allocation"][0]["percent_of_total"] == pytest.approx(100.0)


def test_fractional_units_that_are_not_binary_exact():
    """0.25 is exactly representable in binary; 123.456 is not.

    Also pins the spec formula units * (last_price - average_cost) against the
    implementation's market_value - cost_basis -- algebraically identical, so
    any divergence would be a real defect.
    """
    holding = make_holding(units=123.456, average_cost=19.99, last_price=21.50)
    metrics = calculate_holding_metrics(holding)

    assert metrics["cost_basis"] == pytest.approx(123.456 * 19.99)
    assert metrics["market_value"] == pytest.approx(123.456 * 21.50)
    assert metrics["gain_loss"] == pytest.approx(123.456 * (21.50 - 19.99))
    assert metrics["gain_loss_percent"] == pytest.approx((21.50 - 19.99) / 19.99 * 100)


def test_single_holding_portfolio_is_100_percent_of_its_class():
    holding = make_holding(units=5, average_cost=10, last_price=12, asset_class="Crypto")
    report = build_portfolio_report([holding])

    assert len(report["portfolio"]["asset_class_allocation"]) == 1
    entry = report["portfolio"]["asset_class_allocation"][0]

    assert entry["asset_class"] == "Crypto"
    assert entry["market_value"] == pytest.approx(60.0)
    assert entry["percent_of_total"] == pytest.approx(100.0)
