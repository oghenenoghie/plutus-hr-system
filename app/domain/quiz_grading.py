def grade_quiz(
    correct_option_indices: list[int], answers: list[int], *, passing_score: int
) -> tuple[int, bool]:
    """Scores a quiz attempt as a percentage of questions answered
    correctly, rounded to the nearest whole point, and whether that meets
    passing_score. answers must align 1:1 with correct_option_indices —
    one submitted choice per question, in question order."""
    if len(answers) != len(correct_option_indices):
        raise ValueError("answers must have exactly one entry per question")
    if not correct_option_indices:
        raise ValueError("a quiz needs at least one question to be gradable")

    correct_count = sum(
        1
        for correct, answer in zip(correct_option_indices, answers, strict=True)
        if correct == answer
    )
    score = round(correct_count * 100 / len(correct_option_indices))
    return score, score >= passing_score
