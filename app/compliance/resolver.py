from datetime import date

from app.compliance.models import RuleVersion
from app.compliance.versions.ng_2026_1 import NG_2026_1

_ALL_VERSIONS: tuple[RuleVersion, ...] = (NG_2026_1,)


def resolve_rule_version(country: str, on: date) -> RuleVersion:
    """Resolve the rule version in force for a country on a given date.

    A pay run pins the version it resolves here, so old payslips stay
    reproducible even after a later version supersedes this one.
    """
    for version in _ALL_VERSIONS:
        if version.country != country:
            continue
        if version.effective_from > on:
            continue
        if version.effective_to is not None and version.effective_to <= on:
            continue
        return version
    raise ValueError(f"no rule version found for country={country!r} on={on}")
