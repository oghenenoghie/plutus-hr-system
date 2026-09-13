import pytest

from app.domain.nuban import compute_check_digit, is_valid_nuban


def test_compute_check_digit_matches_cbn_worked_example() -> None:
    # CBN's own published example: bank code 011 (First Bank), serial
    # 000001457 -> check digit 9, full NUBAN 0000014579.
    assert compute_check_digit("011", "000001457") == 9


def test_is_valid_nuban_accepts_the_worked_example() -> None:
    assert is_valid_nuban("011", "0000014579") is True


def test_is_valid_nuban_rejects_a_wrong_check_digit() -> None:
    assert is_valid_nuban("011", "0000014570") is False


def test_is_valid_nuban_rejects_wrong_length() -> None:
    assert is_valid_nuban("011", "123456789") is False
    assert is_valid_nuban("011", "12345678901") is False


def test_is_valid_nuban_rejects_non_digit_characters() -> None:
    assert is_valid_nuban("011", "00000ABCDE") is False


def test_compute_check_digit_rejects_malformed_bank_code() -> None:
    with pytest.raises(ValueError):
        compute_check_digit("11", "000001457")


def test_compute_check_digit_rejects_malformed_serial() -> None:
    with pytest.raises(ValueError):
        compute_check_digit("011", "12345")
