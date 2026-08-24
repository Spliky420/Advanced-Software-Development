def calculate_holding_metrics(holding):
    units = holding["units"]
    average_cost = holding["average_cost"]
    last_price = holding["last_price"]

    cost_basis = units * average_cost
    market_value = units * last_price
    gain_loss = market_value - cost_basis
    gain_loss_percent = (gain_loss / cost_basis * 100) if cost_basis else 0.0

    return {
        "cost_basis": cost_basis,
        "market_value": market_value,
        "gain_loss": gain_loss,
        "gain_loss_percent": gain_loss_percent,
    }


def build_portfolio_report(holdings):
    holdings_detail = []
    total_market_value = 0.0
    total_cost = 0.0
    class_market_values = {}

    for holding in holdings:
        metrics = calculate_holding_metrics(holding)

        total_market_value += metrics["market_value"]
        total_cost += metrics["cost_basis"]

        asset_class = holding["asset_class"]
        class_market_values[asset_class] = class_market_values.get(asset_class, 0.0) + metrics["market_value"]

        detail = dict(holding)
        detail.update(metrics)
        holdings_detail.append(detail)

    total_gain_loss = total_market_value - total_cost

    asset_class_allocation = [
        {
            "asset_class": asset_class,
            "market_value": class_value,
            "percent_of_total": (class_value / total_market_value * 100) if total_market_value else 0.0,
        }
        for asset_class, class_value in class_market_values.items()
    ]

    return {
        "holdings": holdings_detail,
        "portfolio": {
            "total_market_value": total_market_value,
            "total_cost": total_cost,
            "total_gain_loss": total_gain_loss,
            "asset_class_allocation": asset_class_allocation,
        },
    }
