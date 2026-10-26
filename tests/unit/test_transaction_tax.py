from datetime import date

import pytest

from app.compliance.multicountry import TaxConfigurationError
from app.compliance.transaction_tax import (
    IndirectTaxComponent, IndirectTaxRulePack, IndirectTaxRuleStatus,
    TaxTreatment, calculate_indirect_tax,
)

START = date(2026, 1, 1)


def pack(*, status=IndirectTaxRuleStatus.ACTIVE, components=None, country="GH", end=None):
    return IndirectTaxRulePack(
        id="test-pack-v1", country=country, tax_type="vat", effective_from=START,
        effective_to=end, status=status,
        components=tuple(components or [IndirectTaxComponent("VAT", "VAT", 150_000)]),
        source_reference="test fixture only; not statutory guidance",
        approved_by="test-reviewer" if status is IndirectTaxRuleStatus.ACTIVE else None,
    )


def test_exclusive_calculation():
    result = calculate_indirect_tax(country="GH", tax_type="vat", amount_minor=10_000,
                                    rule_pack=pack(), on=date(2026, 4, 1))
    assert (result.net_base_minor, result.total_tax_minor, result.total_minor) == (10_000, 1_500, 11_500)


def test_inclusive_calculation():
    result = calculate_indirect_tax(country="GH", tax_type="vat", amount_minor=11_500,
                                    rule_pack=pack(), on=date(2026, 4, 1), inclusive=True)
    assert (result.net_base_minor, result.total_tax_minor, result.total_minor) == (10_000, 1_500, 11_500)


@pytest.mark.parametrize("treatment", [TaxTreatment.ZERO_RATED, TaxTreatment.EXEMPT, TaxTreatment.OUT_OF_SCOPE])
def test_nonstandard_treatment_does_not_add_tax(treatment):
    result = calculate_indirect_tax(country="GH", tax_type="vat", amount_minor=10_000,
                                    rule_pack=pack(), on=date(2026, 4, 1), treatment=treatment)
    assert result.total_tax_minor == 0
    assert result.total_minor == 10_000


def test_compound_component_uses_previous_tax():
    result = calculate_indirect_tax(
        country="GH", tax_type="vat", amount_minor=10_000,
        rule_pack=pack(components=[
            IndirectTaxComponent("A", "First", 100_000),
            IndirectTaxComponent("B", "Second", 100_000, compound_on_previous=True),
        ]), on=date(2026, 4, 1))
    assert [line.base_minor for line in result.component_lines] == [10_000, 11_000]
    assert [line.amount_minor for line in result.component_lines] == [1_000, 1_100]
    assert result.total_minor == 12_100


def test_draft_pack_fails_closed():
    with pytest.raises(TaxConfigurationError, match="Draft or unapproved"):
        calculate_indirect_tax(country="GH", tax_type="vat", amount_minor=10_000,
                               rule_pack=pack(status=IndirectTaxRuleStatus.DRAFT), on=date(2026, 4, 1))


def test_country_and_tax_type_mismatch_fail_closed():
    with pytest.raises(TaxConfigurationError, match="does not match"):
        calculate_indirect_tax(country="KE", tax_type="vat", amount_minor=10_000,
                               rule_pack=pack(), on=date(2026, 4, 1))
    with pytest.raises(TaxConfigurationError, match="does not match"):
        calculate_indirect_tax(country="GH", tax_type="wht", amount_minor=10_000,
                               rule_pack=pack(), on=date(2026, 4, 1))


def test_effective_to_is_exclusive():
    with pytest.raises(TaxConfigurationError, match="No active rule pack"):
        calculate_indirect_tax(country="GH", tax_type="vat", amount_minor=10_000,
                               rule_pack=pack(end=date(2027, 1, 1)), on=date(2027, 1, 1))


def test_active_pack_requires_approver():
    with pytest.raises(ValueError, match="approved_by"):
        IndirectTaxRulePack(id="bad", country="KE", tax_type="vat", effective_from=START,
                            effective_to=None, status=IndirectTaxRuleStatus.ACTIVE,
                            components=(IndirectTaxComponent("VAT", "VAT", 160_000),),
                            source_reference="fixture", approved_by=None)
