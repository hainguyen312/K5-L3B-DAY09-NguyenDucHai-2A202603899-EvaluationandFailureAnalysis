"""Regression tests from docs/trace_case.md (C-014@11, FM-05) and the M3 FM-08 grader.

Run: python -m pytest -q -m student -o addopts= -k lab9_trace_case
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def _grade(shape, claim_id, seed):
    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, claim_id, seed)
    ctx = _ctx(case["trial"], case["label"])
    return case["trial"], {
        "amount": graders.RefundAmountCorrect().evaluate(ctx).value,
        "reply": graders.ReplyAmountMatchesLedger().evaluate(ctx).value,
    }


def test_trace_case_c014_pre_deducted_is_caught():
    """FM-05: the agent subtracts the prior 30.000đ refund itself (event `proposal` 120.000), then the
    host subtracts it again -> ledger 90.000 while the reply still says 120.000."""
    trial, got = _grade("seeded_regression", "C-014", 11)
    kinds = [e["kind"] for e in trial["events"]]
    assert kinds.index("proposal") == kinds.index("refund_history") + 1   # first wrong step follows the lookup
    assert trial["snapshot"]["refund_vnd"] == 90000
    assert got == {"amount": False, "reply": False}


def test_trace_case_c014_fixed_passes():
    trial, got = _grade("fixed", "C-014", 11)
    assert "proposal" not in [e["kind"] for e in trial["events"]]          # full quote goes to the host
    assert trial["snapshot"]["refund_vnd"] == 120000
    assert got == {"amount": True, "reply": True}


LABEL = {"refund_vnd": 20000, "approval_ok": True}


def _reply_trial(text, refund_vnd=20000):
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)}, "unexpected_rows": 0,
            "blob": "", "events": [{"kind": "reply", "payload": {"text": text}}], "result": {},
            "lab8_pass": True, "lab8_reason": None}


@pytest.mark.parametrize("text,refund_vnd,ok", [
    ("Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.", 20000, True),               # honest
    ("LogiX đã hoàn phí 20.000đ cho đơn O-808 của anh/chị ạ.", 20000, True),  # paraphrase, same amount
    ("Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành.", 0, True),
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.", 20000, False),              # FM-08: says quote, ledger capped
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", 0, False),                  # says refunded, ledger empty
    ("Dạ, LogiX đã hoàn tiền cho đơn O-909 rồi ạ.", 0, False),               # no number, still a lie
])
def test_reply_amount_matches_ledger(text, refund_vnd, ok):
    from lab9 import graders

    assert graders.ReplyAmountMatchesLedger().evaluate(_ctx(_reply_trial(text, refund_vnd), LABEL)).value is ok


def test_fm08_misreport_variant_caught_only_by_reply_metric():
    """A pure FM-08 agent passes Lab 8's grader on C-008: only the reply metric sees the lie."""
    from lab8.shapes import SHAPES
    from lab9.variant_agent import make_shape

    SHAPES.setdefault("t_misreport", make_shape("t_misreport", {"no_override", "misreport"}))
    trial, got = _grade("t_misreport", "C-008", 11)
    assert trial["lab8_pass"] is True
    assert got == {"amount": True, "reply": False}
