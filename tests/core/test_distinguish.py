"""distinguishes(): does a decision question's Yes/No change the verdict?"""

from datetime import timedelta

from haqwa.core.compiler import distinguishes
from haqwa.core.spec import AllowIf, Condition, ResetAfter, TimelineEvent

from .helpers import amo, wt

INSTALLMENT = AllowIf(allow_if=Condition(field="payment_type", op="eq", value="installment"))


def t(event: str, hours: float | None = None, **data: str) -> TimelineEvent:
    at = None if hours is None else timedelta(hours=hours)
    return TimelineEvent(event=event, data=data, at=at)


def test_refund_reset_is_testable() -> None:
    timeline = [t("charged"), t("refunded"), t("charged")]
    assert distinguishes(amo(), ResetAfter(reset_after="refunded"), timeline)


def test_installment_allow_if_is_testable() -> None:
    timeline = [t("charged", payment_type="installment")] * 2
    assert distinguishes(amo(), INSTALLMENT, timeline)


def test_within_time_without_time_is_not_testable() -> None:
    # Gemini's "installment refund left open past 24 hours" with no time in the timeline:
    # the deadline never passes, so Yes and No both pass.
    timeline = [t("refund_requested", payment_type="installment")]
    assert not distinguishes(wt(), INSTALLMENT, timeline)


def test_second_request_without_time_is_not_testable() -> None:
    timeline = [t("refund_requested"), t("refund_requested")]
    assert not distinguishes(wt(), ResetAfter(reset_after="refund_requested"), timeline)


def test_within_time_with_time_is_testable() -> None:
    timeline = [
        t("refund_requested", 0, payment_type="installment"),
        t("refund_completed", 49, payment_type="installment"),
    ]
    assert distinguishes(wt(), INSTALLMENT, timeline)


def test_exception_already_on_the_rule_is_not_testable() -> None:
    rule = amo(**{"except": [{"reset_after": "refunded"}]})
    timeline = [t("charged"), t("refunded"), t("charged")]
    assert not distinguishes(rule, ResetAfter(reset_after="refunded"), timeline)


def test_rule_is_not_changed() -> None:
    rule = amo()
    distinguishes(rule, ResetAfter(reset_after="refunded"), [t("charged")])
    assert rule.exceptions == []
