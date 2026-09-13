from typing import Any

MASKED_COMPENSATION_FIELDS = (
    "basic_minor",
    "housing_minor",
    "transport_minor",
    "other_earnings_minor",
    "annual_rent_paid_minor",
)


def mask_compensation(data: dict[str, Any], *, mask: bool) -> dict[str, Any]:
    """Replaces every compensation field with None when mask is True,
    leaving every other field untouched. The caller decides mask based on
    who's viewing — never the record's own owner, only someone who can see
    it without being entitled to its pay figures (a MANAGER viewing a
    direct report's Employee record)."""
    if not mask:
        return data
    return {**data, **dict.fromkeys(MASKED_COMPENSATION_FIELDS, None)}
