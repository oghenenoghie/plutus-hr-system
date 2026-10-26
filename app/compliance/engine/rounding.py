"""Exact rounding for the engine: every amount is worked out as an exact
fraction and rounded once, so rounding to a coarser increment (whole francs,
whole hundreds) never rounds twice."""

from app.compliance.engine.rules import PPM, Rounding, RoundingMode


def round_ratio(numerator: int, denominator: int, rounding: Rounding) -> int:
    """numerator / denominator minor units, rounded to a whole multiple of
    the rounding increment. With HALF_UP and an increment of 1 this is
    exactly app.domain.money.apply_rate_ppm's rule."""
    if numerator < 0:
        raise ValueError("numerator must not be negative")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    unit = denominator * rounding.increment_minor
    whole, remainder = divmod(numerator, unit)
    if rounding.mode is RoundingMode.UP:
        whole += remainder > 0
    elif rounding.mode is RoundingMode.HALF_UP:
        whole += 2 * remainder >= unit
    return whole * rounding.increment_minor


def rate_amount(base_minor: int, rate_ppm: int, rounding: Rounding) -> int:
    if base_minor < 0:
        raise ValueError("base_minor must not be negative")
    return round_ratio(base_minor * rate_ppm, PPM, rounding)
