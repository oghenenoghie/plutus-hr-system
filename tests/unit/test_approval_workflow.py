from app.domain.approval_workflow import ApprovalRequestStatus, StepDecision, advance


def test_approval_before_last_step_moves_to_next_step() -> None:
    step, status = advance(1, 3, StepDecision.APPROVED)
    assert step == 2
    assert status == ApprovalRequestStatus.PENDING


def test_approval_at_last_step_completes_the_request() -> None:
    step, status = advance(3, 3, StepDecision.APPROVED)
    assert step == 3
    assert status == ApprovalRequestStatus.APPROVED


def test_rejection_at_any_step_ends_the_chain_immediately() -> None:
    step, status = advance(1, 3, StepDecision.REJECTED)
    assert step == 1
    assert status == ApprovalRequestStatus.REJECTED
