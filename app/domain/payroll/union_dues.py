def union_dues_deduction_minor(monthly_dues_minor: int, *, available_net_minor: int) -> int:
    """Flat monthly union dues, skipped whole (never partially deducted) if
    they'd exceed what's left after loans and benefits — checked last in
    the deduction order (statutory -> loans -> benefits -> union dues) so
    a statutory or benefit deduction is never squeezed out to make room
    for dues instead.
    """
    if monthly_dues_minor < 0:
        raise ValueError("monthly_dues_minor must not be negative")
    return monthly_dues_minor if monthly_dues_minor <= available_net_minor else 0
