import enum


class ApprovalRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StepDecision(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


def advance(
    current_step: int, total_steps: int, decision: StepDecision
) -> tuple[int, ApprovalRequestStatus]:
    """Given the step just decided, returns (next_step, new_overall_status).
    A rejection at any step ends the whole chain immediately — there's no
    partial approval. An approval at the last step ends it too, as an
    overall approval; anywhere before that, it just moves to the next
    step and the request stays pending."""
    if decision == StepDecision.REJECTED:
        return current_step, ApprovalRequestStatus.REJECTED
    if current_step >= total_steps:
        return current_step, ApprovalRequestStatus.APPROVED
    return current_step + 1, ApprovalRequestStatus.PENDING
