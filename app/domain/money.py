from dataclasses import dataclass

# Pan-African: resolve the exponent per currency — never assume 2. Kobo (NGN)
# is the only entry until a second country's rule set needs another.
_CURRENCY_EXPONENTS: dict[str, int] = {"NGN": 2}


def minor_units_exponent(currency: str) -> int:
    try:
        return _CURRENCY_EXPONENTS[currency]
    except KeyError as exc:
        raise ValueError(f"unknown currency exponent for {currency!r}") from exc


def apply_rate_ppm(amount_minor: int, rate_ppm: int) -> int:
    """Apply a parts-per-million rate to an integer minor-unit amount.

    Round-half-up: (amount * rate + 500_000) // 1_000_000. This is the one
    documented rounding rule for the whole compliance engine — every band
    boundary in tests/golden/test_paye.py is tested against it.
    """
    if amount_minor < 0:
        raise ValueError("amount_minor must not be negative")
    if rate_ppm < 0:
        raise ValueError("rate_ppm must not be negative")
    return (amount_minor * rate_ppm + 500_000) // 1_000_000


@dataclass(frozen=True)
class Money:
    amount_minor: int
    currency: str = "NGN"

    def __post_init__(self) -> None:
        minor_units_exponent(self.currency)  # raises on an unknown currency

    def _require_same_currency(self, other: "Money") -> None:
        if other.currency != self.currency:
            raise ValueError(f"cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def display(self) -> str:
        exponent = minor_units_exponent(self.currency)
        major = self.amount_minor / (10**exponent)
        return f"{major:.{exponent}f} {self.currency}"
