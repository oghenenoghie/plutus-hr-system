from app.domain.salary_masking import mask_compensation


def test_mask_true_nulls_only_compensation_fields() -> None:
    data = {
        "id": "abc",
        "basic_minor": 100,
        "housing_minor": 50,
        "transport_minor": 20,
        "other_earnings_minor": 5,
        "annual_rent_paid_minor": 10,
    }
    masked = mask_compensation(data, mask=True)
    assert masked["id"] == "abc"
    assert masked["basic_minor"] is None
    assert masked["housing_minor"] is None
    assert masked["transport_minor"] is None
    assert masked["other_earnings_minor"] is None
    assert masked["annual_rent_paid_minor"] is None


def test_mask_false_is_a_no_op() -> None:
    data = {"basic_minor": 100}
    assert mask_compensation(data, mask=False) == data
