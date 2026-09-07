def compute_leave_balance(entitlement_days: int, approved_days_taken: int) -> int:
    """Remaining leave days, floored at zero. Never negative — a request
    that would overdraw the balance is a policy decision for the caller
    (e.g. the approval step), not something this function silently allows."""
    if entitlement_days < 0:
        raise ValueError("entitlement_days must not be negative")
    if approved_days_taken < 0:
        raise ValueError("approved_days_taken must not be negative")
    return max(0, entitlement_days - approved_days_taken)
