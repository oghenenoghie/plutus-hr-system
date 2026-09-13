import pytest

from app.domain.quiz_grading import grade_quiz


def test_perfect_score_passes() -> None:
    score, passed = grade_quiz([0, 1, 2], [0, 1, 2], passing_score=70)
    assert score == 100
    assert passed is True


def test_partial_score_below_threshold_fails() -> None:
    score, passed = grade_quiz([0, 1, 2], [0, 0, 0], passing_score=70)
    assert score == 33
    assert passed is False


def test_score_exactly_at_threshold_passes() -> None:
    score, passed = grade_quiz([0, 1], [0, 1], passing_score=100)
    assert score == 100
    assert passed is True


def test_mismatched_answer_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="one entry per question"):
        grade_quiz([0, 1], [0], passing_score=50)


def test_empty_quiz_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one question"):
        grade_quiz([], [], passing_score=50)
