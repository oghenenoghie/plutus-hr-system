/**
 * Plutus Technologies — Multi-country tax engine foundation.
 *
 * This module provides jurisdiction selection and a deterministic VAT calculator.
 * It deliberately contains no production tax rates: country rates, taxability,
 * exemptions, registration thresholds and rounding rules must be validated from
 * current legislation before a rule is approved.
 */

export const SUPPORTED_COUNTRIES = ["NG", "GM", "GH", "RW", "CI", "KE"] as const;
export type CountryCode = (typeof SUPPORTED_COUNTRIES)[number];

export type TaxCategory =
  | "VAT"
  | "PAYE"
  | "CORPORATE_INCOME"
  | "WITHHOLDING"
  | "SOCIAL_SECURITY"
  | "OTHER_LEVY";

export type TaxRuleStatus = "draft" | "approved" | "retired";

export interface CountryDefinition {
  code: CountryCode;
  name: string;
  currency: string;
}

export interface TaxRule {
  id: string;
  countryCode: CountryCode;
  category: TaxCategory;
  name: string;
  /** Rate in basis points: 1500 = 15%. Null means not configured. */
  rateBasisPoints: number | null;
  status: TaxRuleStatus;
  effectiveFrom: string;
  effectiveTo?: string;
  sourceUrl?: string;
  verifiedAt?: string;
  approvedBy?: string;
  version: number;
  notes?: string;
}

export interface VatCalculationInput {
  countryCode: CountryCode;
  taxRuleId: string;
  transactionDate: string;
  /** Amount in the currency's minor units (integer arithmetic only). */
  amountMinor: bigint;
  /** If true, amountMinor already includes VAT. */
  taxInclusive: boolean;
}

export interface VatCalculationResult {
  countryCode: CountryCode;
  taxRuleId: string;
  ruleVersion: number;
  taxableAmountMinor: bigint;
  taxAmountMinor: bigint;
  totalAmountMinor: bigint;
  rateBasisPoints: number;
  currency: string;
}

export class TaxConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TaxConfigurationError";
  }
}

/**
 * ISO 4217 currency codes are provided as defaults. Verify currency precision
 * with the application's money/currency library; not all currencies use two
 * decimal places, and KWD uses three.
 */
export const COUNTRY_DEFINITIONS: Record<CountryCode, CountryDefinition> = {
  NG: { code: "NG", name: "Nigeria", currency: "NGN" },
  GM: { code: "GM", name: "The Gambia", currency: "GMD" },
  GH: { code: "GH", name: "Ghana", currency: "GHS" },
  RW: { code: "RW", name: "Rwanda", currency: "RWF" },
  CI: { code: "CI", name: "Côte d'Ivoire", currency: "XOF" },
  KE: { code: "KE", name: "Kenya", currency: "KES" },
};

/**
 * Keep the registry empty until rules are imported from the existing Nigeria
 * implementation or reviewed and approved for the relevant jurisdiction.
 * In production, load rules from the database rather than editing this file.
 */
export const INITIAL_TAX_RULES: readonly TaxRule[] = [];

function isValidIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.valueOf()) &&
    parsed.toISOString().slice(0, 10) === value;
}

function roundRatio(numerator: bigint, denominator: bigint): bigint {
  if (denominator <= 0n) {
    throw new TaxConfigurationError("Calculation denominator must be positive.");
  }
  if (numerator < 0n) {
    throw new TaxConfigurationError(
      "Negative amounts must be handled by the credit-note workflow.",
    );
  }
  return (numerator + denominator / 2n) / denominator;
}

export function findApplicableTaxRule(
  rules: readonly TaxRule[],
  countryCode: CountryCode,
  category: TaxCategory,
  ruleId: string,
  transactionDate: string,
): TaxRule {
  if (!isValidIsoDate(transactionDate)) {
    throw new TaxConfigurationError("Transaction date must use YYYY-MM-DD.");
  }

  const rule = rules.find(
    (candidate) =>
      candidate.id === ruleId &&
      candidate.countryCode === countryCode &&
      candidate.category === category,
  );

  if (!rule) {
    throw new TaxConfigurationError(
      `No ${category} rule ${ruleId} is configured for ${countryCode}.`,
    );
  }

  if (rule.status !== "approved") {
    throw new TaxConfigurationError(
      `Tax rule ${rule.id} is not approved for production use.`,
    );
  }

  if (
    !isValidIsoDate(rule.effectiveFrom) ||
    (rule.effectiveTo !== undefined && !isValidIsoDate(rule.effectiveTo))
  ) {
    throw new TaxConfigurationError(`Tax rule ${rule.id} has invalid dates.`);
  }

  if (
    transactionDate < rule.effectiveFrom ||
    (rule.effectiveTo !== undefined && transactionDate > rule.effectiveTo)
  ) {
    throw new TaxConfigurationError(
      `Tax rule ${rule.id} is not effective on ${transactionDate}.`,
    );
  }

  return rule;
}

/**
 * Calculate VAT for a transaction already classified as taxable.
 *
 * This function does not decide whether a supply is taxable. The caller must
 * first apply country-specific taxability, exemption, zero-rating, place-of-
 * supply and registration rules.
 */
export function calculateVat(
  input: VatCalculationInput,
  rules: readonly TaxRule[] = INITIAL_TAX_RULES,
): VatCalculationResult {
  if (input.amountMinor < 0n) {
    throw new TaxConfigurationError(
      "Negative amounts must use the credit-note workflow.",
    );
  }

  const country = COUNTRY_DEFINITIONS[input.countryCode];
  if (!country) {
    throw new TaxConfigurationError(
      `Unsupported country code: ${input.countryCode}`,
    );
  }

  const rule = findApplicableTaxRule(
    rules,
    input.countryCode,
    "VAT",
    input.taxRuleId,
    input.transactionDate,
  );

  const rate = rule.rateBasisPoints;
  if (
    rate === null ||
    !Number.isSafeInteger(rate) ||
    rate < 0 ||
    rate > 100_000
  ) {
    throw new TaxConfigurationError(
      `VAT rate is missing or invalid for rule ${rule.id}.`,
    );
  }

  const rateBigInt = BigInt(rate);
  const basisPointsPerWhole = 10_000n;

  let taxableAmountMinor: bigint;
  let taxAmountMinor: bigint;
  let totalAmountMinor: bigint;

  if (input.taxInclusive) {
    taxAmountMinor = roundRatio(
      input.amountMinor * rateBigInt,
      basisPointsPerWhole + rateBigInt,
    );
    taxableAmountMinor = input.amountMinor - taxAmountMinor;
    totalAmountMinor = input.amountMinor;
  } else {
    taxableAmountMinor = input.amountMinor;
    taxAmountMinor = roundRatio(
      taxableAmountMinor * rateBigInt,
      basisPointsPerWhole,
    );
    totalAmountMinor = taxableAmountMinor + taxAmountMinor;
  }

  return {
    countryCode: input.countryCode,
    taxRuleId: rule.id,
    ruleVersion: rule.version,
    taxableAmountMinor,
    taxAmountMinor,
    totalAmountMinor,
    rateBasisPoints: rate,
    currency: country.currency,
  };
}
