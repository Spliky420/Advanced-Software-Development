from datetime import date

ASSET_CLASSES = (
    "Australian equities",
    "International equities",
    "ETFs",
    "REITs",
    "Government bonds",
    "Corporate bonds",
    "Cash",
    "Term deposits",
    "Commodities",
    "Crypto",
)


class ValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__("; ".join(self.errors))


def _is_positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _check_date(value, field_name, errors, required):
    if value is None or value == "":
        if required:
            errors.append(f"{field_name} is required")
        return
    if not isinstance(value, str):
        errors.append(f"{field_name} must be a date string in YYYY-MM-DD format")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field_name} must be a valid date in YYYY-MM-DD format")


def validate_holding_payload(data):
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    errors = []

    ticker = data.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip():
        errors.append("ticker is required and cannot be empty")

    asset_name = data.get("asset_name")
    if not isinstance(asset_name, str) or not asset_name.strip():
        errors.append("asset_name is required and cannot be empty")

    asset_class = data.get("asset_class")
    if asset_class not in ASSET_CLASSES:
        errors.append("asset_class must be one of: " + ", ".join(ASSET_CLASSES))

    if not _is_positive_number(data.get("units")):
        errors.append("units must be a positive number")

    if not _is_positive_number(data.get("average_cost")):
        errors.append("average_cost must be a positive number")

    if not _is_positive_number(data.get("last_price")):
        errors.append("last_price must be a positive number")

    currency = data.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        errors.append("currency is required and cannot be empty")

    _check_date(data.get("purchase_date"), "purchase_date", errors, required=True)
    _check_date(data.get("price_as_at"), "price_as_at", errors, required=False)

    notes = data.get("notes")
    if notes is not None and not isinstance(notes, str):
        errors.append("notes must be a string")

    if errors:
        raise ValidationError(errors)

    return {
        "ticker": ticker.strip(),
        "asset_name": asset_name.strip(),
        "asset_class": asset_class,
        "units": float(data["units"]),
        "average_cost": float(data["average_cost"]),
        "currency": currency.strip(),
        "last_price": float(data["last_price"]),
        "price_as_at": data.get("price_as_at") or None,
        "purchase_date": data["purchase_date"],
        "notes": notes,
    }


TARGET_SUM_TOLERANCE = 0.01


def validate_targets_payload(data):
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    errors = []

    targets = data.get("targets")
    clean_targets = []
    if not isinstance(targets, list) or not targets:
        errors.append("targets is required and must be a non-empty list")
    else:
        seen_classes = set()
        for index, item in enumerate(targets):
            if not isinstance(item, dict):
                errors.append(f"targets[{index}] must be an object")
                continue

            asset_class = item.get("asset_class")
            target_percent = item.get("target_percent")

            if asset_class not in ASSET_CLASSES:
                errors.append(f"targets[{index}].asset_class must be one of: " + ", ".join(ASSET_CLASSES))
            elif asset_class in seen_classes:
                errors.append(f"targets[{index}].asset_class '{asset_class}' is duplicated")
            else:
                seen_classes.add(asset_class)

            if (
                not isinstance(target_percent, (int, float))
                or isinstance(target_percent, bool)
                or target_percent < 0
            ):
                errors.append(f"targets[{index}].target_percent must be a non-negative number")
            elif asset_class in ASSET_CLASSES:
                clean_targets.append({"asset_class": asset_class, "target_percent": float(target_percent)})

        if not errors:
            total = sum(t["target_percent"] for t in clean_targets)
            if abs(total - 100) > TARGET_SUM_TOLERANCE:
                errors.append(f"target_percent values must sum to 100 (got {total:.2f})")

    if errors:
        raise ValidationError(errors)

    return clean_targets
