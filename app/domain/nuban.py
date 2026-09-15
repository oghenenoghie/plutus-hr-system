"""Nigeria Uniform Bank Account Number (NUBAN) check-digit validation.

A curated list, not exhaustive — the ~20 major deposit money banks with a
stable, widely-published 3-digit CBN/NIP code. An employee's bank not on
this list falls back to format-only validation (exactly 10 digits) with no
checksum, rather than blocking the record: the check digit confirms
internal consistency of a *known* bank's number, it is not a live
account-name lookup against the bank.
"""

# name -> 3-digit CBN/NIP bank code. Verified against multiple independent
# fintech integration references (Paystack/Flutterwave/NIBSS-adjacent docs),
# not invented — these codes are stable public routing identifiers, not
# versioned statutory figures.
NIGERIAN_BANKS: dict[str, str] = {
    "Access Bank": "044",
    "Citibank Nigeria": "023",
    "Ecobank Nigeria": "050",
    "Fidelity Bank": "070",
    "First Bank of Nigeria": "011",
    "First City Monument Bank": "214",
    "Globus Bank": "103",
    "Guaranty Trust Bank": "058",
    "Heritage Bank": "030",
    "Jaiz Bank": "301",
    "Keystone Bank": "082",
    "Polaris Bank": "076",
    "Providus Bank": "101",
    "Stanbic IBTC Bank": "221",
    "Standard Chartered Bank": "068",
    "Sterling Bank": "232",
    "TAJ Bank": "302",
    "Union Bank of Nigeria": "032",
    "United Bank for Africa": "033",
    "Unity Bank": "215",
    "Wema Bank": "035",
    "Zenith Bank": "057",
}

# The published CBN check-digit weights, applied to the 12-digit string
# formed by the 3-digit bank code followed by the first 9 digits of the
# account number. Golden-tested against the CBN's own worked example
# (bank code 011, serial 000001457 -> check digit 9, full NUBAN
# 0000014579) in tests/unit/test_nuban.py.
_WEIGHTS = (3, 7, 3, 3, 7, 3, 3, 7, 3, 3, 7, 3)


def compute_check_digit(bank_code: str, account_serial: str) -> int:
    """bank_code: 3 digits. account_serial: the first 9 digits of the
    10-digit account number (i.e. every digit except the check digit
    itself)."""
    if len(bank_code) != 3 or not bank_code.isdigit():
        raise ValueError("bank_code must be exactly 3 digits")
    if len(account_serial) != 9 or not account_serial.isdigit():
        raise ValueError("account_serial must be exactly 9 digits")
    digits = [int(d) for d in bank_code + account_serial]
    total = sum(digit * weight for digit, weight in zip(digits, _WEIGHTS, strict=True))
    return (10 - (total % 10)) % 10


def is_valid_nuban(bank_code: str, account_number: str) -> bool:
    """True if account_number's own check digit (its 10th, last digit)
    matches what compute_check_digit derives from the other nine."""
    if len(account_number) != 10 or not account_number.isdigit():
        return False
    return compute_check_digit(bank_code, account_number[:9]) == int(account_number[9])
