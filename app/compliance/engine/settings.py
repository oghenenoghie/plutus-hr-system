"""Figures an organisation enters itself, under Tax Settings.

A country's rule set is approved with every figure its sources settle.
Where they didn't (a figure no source gave, or sources that disagree), the
rule set is a RuleSetTemplate: it names the figures it needs as
SettingSpecs, and builds the CountryRuleSet from each organisation's own
values. Each option a spec offers is a value some source gave, with that
source, so the organisation chooses knowingly; nothing is filled in for it.

Values are stored as text in a fixed form: a percentage as parts per
million, an amount in the currency's minor units, a due day as the day of
the following month, a choice as the option's value.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from app.compliance.engine.rules import PPM, CountryRuleSet
from app.domain.money import minor_units_exponent


class SettingKind(StrEnum):
    PERCENT = "percent"  # stored in parts per million: 5.75% is "57500"
    AMOUNT = "amount"  # stored in the currency's minor units
    DAY = "day"  # a day of the following month, 1 to 28
    CHOICE = "choice"  # one of the options' values


@dataclass(frozen=True, slots=True)
class SettingOption:
    value: str  # in stored form
    label: str
    source: str  # the source that gives this value, or why it is offered


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    label: str
    help: str  # why the organisation is asked: what the sources say
    kind: SettingKind
    # For a choice, the only values allowed. For the other kinds,
    # suggestions the sources give; any valid value may be entered.
    options: tuple[SettingOption, ...] = ()
    minimum: int | None = None  # in stored form
    maximum: int | None = None
    # Asked only while another setting has this value, e.g. a levy's due
    # day only when the organisation pays the levy.
    required_when: tuple[str, str] | None = None


SettingValues = Mapping[str, str]


class SettingError(ValueError):
    """A value that isn't valid for its setting."""


_DAY_RANGE = (1, 28)


def _decimal(entered: str) -> Decimal:
    try:
        value = Decimal(entered.strip().rstrip("%").replace(",", "").strip())
    except InvalidOperation as exc:
        raise SettingError(f"{entered!r} isn't a number") from exc
    if not value.is_finite():
        raise SettingError(f"{entered!r} isn't a number")
    return value


def _bounds(spec: SettingSpec) -> tuple[int | None, int | None]:
    if spec.kind is SettingKind.PERCENT:
        low, high = 0, PPM
    elif spec.kind is SettingKind.AMOUNT:
        low, high = 0, None
    elif spec.kind is SettingKind.DAY:
        low, high = _DAY_RANGE
    else:
        return None, None
    return (
        low if spec.minimum is None else max(low, spec.minimum),
        high if spec.maximum is None else spec.maximum if high is None else min(high, spec.maximum),
    )


def parse_setting(spec: SettingSpec, entered: str, *, currency: str) -> str:
    """The stored form of a value as a person enters it: a percentage
    ("5.75"), an amount in the currency ("1500.00"), a day ("15") or an
    option's value. Raises SettingError for anything else."""
    if spec.kind is SettingKind.CHOICE:
        allowed = {option.value for option in spec.options}
        if entered not in allowed:
            raise SettingError(f"{spec.label}: choose one of {', '.join(sorted(allowed))}")
        return entered
    number = _decimal(entered)
    if spec.kind is SettingKind.PERCENT:
        scaled = number * 10_000
        what = "a percentage to at most four decimal places"
    elif spec.kind is SettingKind.AMOUNT:
        exponent = minor_units_exponent(currency)
        scaled = number * (10**exponent)
        what = f"an amount in {currency} to at most {exponent} decimal places"
    else:
        scaled = number
        what = "a whole day of the month"
    if scaled != scaled.to_integral_value():
        raise SettingError(f"{spec.label}: enter {what}")
    stored = int(scaled)
    low, high = _bounds(spec)
    if (low is not None and stored < low) or (high is not None and stored > high):
        lowest = display_setting(spec, str(low), currency=currency)
        if high is None:
            raise SettingError(f"{spec.label}: must be at least {lowest}")
        highest = display_setting(spec, str(high), currency=currency)
        raise SettingError(f"{spec.label}: must be between {lowest} and {highest}")
    return str(stored)


def display_setting(spec: SettingSpec, stored: str, *, currency: str) -> str:
    """A stored value as a person reads it."""
    if spec.kind is SettingKind.CHOICE:
        return next((option.label for option in spec.options if option.value == stored), stored)
    if spec.kind is SettingKind.PERCENT:
        percent = Decimal(int(stored)) / 10_000
        return f"{percent.normalize():f}%"
    if spec.kind is SettingKind.AMOUNT:
        exponent = minor_units_exponent(currency)
        major = Decimal(int(stored)).scaleb(-exponent)
        return f"{major:,.{exponent}f} {currency}"
    return stored


def entry_text(spec: SettingSpec, stored: str, *, currency: str) -> str:
    """A stored value as a person would enter it, so parse_setting gives it
    back: "5.75", "1500.00", "15", or the option's value."""
    if spec.kind is SettingKind.PERCENT:
        return f"{(Decimal(int(stored)) / 10_000).normalize():f}"
    if spec.kind is SettingKind.AMOUNT:
        exponent = minor_units_exponent(currency)
        return f"{Decimal(int(stored)).scaleb(-exponent):.{exponent}f}"
    return stored


def is_required(spec: SettingSpec, values: SettingValues) -> bool:
    if spec.required_when is None:
        return True
    key, value = spec.required_when
    return values.get(key) == value


def missing_settings(specs: tuple[SettingSpec, ...], values: SettingValues) -> list[SettingSpec]:
    return [spec for spec in specs if is_required(spec, values) and spec.key not in values]


def setting_int(values: SettingValues, key: str) -> int:
    return int(values[key])


@dataclass(frozen=True)
class RuleSetTemplate:
    """A country's approved rule set, apart from the figures each
    organisation enters itself: `build` makes the CountryRuleSet from them.
    Resolved, like a CountryRuleSet, only through the registry."""

    id: str
    country: str
    effective_from: date
    effective_to: date | None
    settings: tuple[SettingSpec, ...]
    build: Callable[[SettingValues], CountryRuleSet]
    # For the organisation: what is built in, what it enters, and what isn't
    # modelled.
    summary: str = ""

    def applies_on(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on < self.effective_to)

    def spec(self, key: str) -> SettingSpec | None:
        return next((spec for spec in self.settings if spec.key == key), None)

    def preview_values(self) -> dict[str, str]:
        """Every setting at its first option, or its lowest value: enough
        to build the rule set for checking its structure and describing the
        figures that don't depend on settings. Never used for a payslip."""
        values: dict[str, str] = {}
        for spec in self.settings:
            if spec.options:
                values[spec.key] = spec.options[0].value
            else:
                low, _ = _bounds(spec)
                values[spec.key] = str(low or 0)
        return values


def settings_problems(template: RuleSetTemplate) -> list[str]:
    """A template's settings: unique keys, options valid for their kind,
    and conditions that name another setting."""
    problems: list[str] = []
    keys = [spec.key for spec in template.settings]
    if len(keys) != len(set(keys)):
        problems.append(f"{template.id}: setting keys must be unique")
    for spec in template.settings:
        where = f"{template.id} setting {spec.key}"
        if not (spec.key and spec.label and spec.help):
            problems.append(f"{where}: needs a key, a label and help")
        if spec.kind is SettingKind.CHOICE and len(spec.options) < 2:
            problems.append(f"{where}: a choice needs at least two options")
        low, high = _bounds(spec)
        for option in spec.options:
            if spec.kind is SettingKind.CHOICE:
                continue
            try:
                stored = int(option.value)
            except ValueError:
                problems.append(f"{where}: option {option.value!r} isn't in stored form")
                continue
            if (low is not None and stored < low) or (high is not None and stored > high):
                problems.append(f"{where}: option {option.value!r} is out of range")
        if spec.required_when is not None:
            other, value = spec.required_when
            target = template.spec(other)
            if target is None or target.kind is not SettingKind.CHOICE:
                problems.append(f"{where}: required_when must name a choice setting")
            elif value not in {option.value for option in target.options}:
                problems.append(f"{where}: required_when names an option {other} doesn't have")
    return problems
