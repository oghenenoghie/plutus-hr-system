import enum


class PayRunType(str, enum.Enum):
    """What kind of pay run this is, independent of its recurring
    frequency (PayFrequency). REGULAR is the default recurring run; the
    other four exist so a one-off run can be labelled honestly rather than
    disguised as a REGULAR run with an odd gross — which is also what a
    reviewer needs to see before deciding whether a variance flag on the
    run is expected (a bonus run legitimately swings gross) or a mistake.
    """

    REGULAR = "regular"
    BONUS = "bonus"
    THIRTEENTH_MONTH = "thirteenth_month"
    ARREARS = "arrears"
    OFF_CYCLE = "off_cycle"
