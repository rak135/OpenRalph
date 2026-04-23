"""Tests for the bounded text result contract and deterministic parser.

Phase 3 mandate: the loop must not rely on vendor-native JSON as the source
of truth for iteration outcomes. Instead it uses a local deterministic parser
against a narrow, explicit text block format.

These tests verify:
  - successful parse of a well-formed block
  - that all five fields are required
  - that field values are validated
  - that the consistent-state rule (complete=true requires status=done) holds
  - that multiple blocks or missing blocks produce UntrustedResult
  - that UntrustedResult never masquerades as success
  - completion_confidence values on both types
"""

from __future__ import annotations

import pytest

from openralph_py.result_contract import (
    UntrustedResult,
    WorkerResultBlock,
    parse_worker_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(**overrides: str) -> str:
    """Return a well-formed output string containing one <ralph-result> block."""
    fields = {
        "status": "done",
        "summary": "implemented the feature",
        "verification": "ran pytest, 5 passed",
        "complete": "true",
        "blocker": "none",
    }
    fields.update(overrides)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"Some worker output.\n<ralph-result>\n{body}\n</ralph-result>\nTrailing text."


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_parse_well_formed_block_returns_worker_result_block():
    result = parse_worker_result(_make_block())
    assert isinstance(result, WorkerResultBlock)
    assert result.is_trusted is True
    assert result.status == "done"
    assert result.summary == "implemented the feature"
    assert result.verification == "ran pytest, 5 passed"
    assert result.complete is True
    assert result.blocker == "none"


def test_parse_blocked_status():
    output = _make_block(status="blocked", complete="false", blocker="test suite broken")
    result = parse_worker_result(output)
    assert isinstance(result, WorkerResultBlock)
    assert result.status == "blocked"
    assert result.complete is False
    assert result.blocker == "test suite broken"
    assert result.completion_confidence == "promise-denied"


def test_parse_partial_status():
    result = parse_worker_result(_make_block(status="partial", complete="false"))
    assert isinstance(result, WorkerResultBlock)
    assert result.status == "partial"


def test_parse_error_status():
    result = parse_worker_result(_make_block(status="error", complete="false"))
    assert isinstance(result, WorkerResultBlock)
    assert result.status == "error"


def test_completion_confidence_promise_confirmed_when_done_and_complete():
    result = parse_worker_result(_make_block(status="done", complete="true"))
    assert isinstance(result, WorkerResultBlock)
    assert result.completion_confidence == "promise-confirmed"


def test_completion_confidence_promise_denied_when_not_complete():
    result = parse_worker_result(_make_block(status="done", complete="false"))
    assert isinstance(result, WorkerResultBlock)
    assert result.completion_confidence == "promise-denied"


def test_case_insensitive_block_tags():
    """The block tag regex should match regardless of tag case."""
    output = "<RALPH-RESULT>\nstatus: done\nsummary: x\nverification: y\ncomplete: true\nblocker: none\n</RALPH-RESULT>"
    result = parse_worker_result(output)
    assert isinstance(result, WorkerResultBlock)


def test_block_with_extra_whitespace_lines():
    """Blank lines inside the block body are ignored."""
    output = (
        "<ralph-result>\n"
        "  status: done\n"
        "\n"
        "  summary: did something\n"
        "  verification: manual check\n"
        "  complete: true\n"
        "  blocker: none\n"
        "</ralph-result>"
    )
    result = parse_worker_result(output)
    assert isinstance(result, WorkerResultBlock)
    assert result.summary == "did something"


def test_summary_with_colon_preserves_value():
    """Values that themselves contain colons must be preserved correctly."""
    output = _make_block(summary="ran: pytest and mypy")
    result = parse_worker_result(output)
    assert isinstance(result, WorkerResultBlock)
    assert result.summary == "ran: pytest and mypy"


# ---------------------------------------------------------------------------
# Failure paths — missing block
# ---------------------------------------------------------------------------


def test_no_block_returns_untrusted():
    result = parse_worker_result("Some worker output with no block.")
    assert isinstance(result, UntrustedResult)
    assert result.is_trusted is False
    assert result.complete is False
    assert "no <ralph-result> block" in result.reason


def test_empty_stdout_returns_untrusted():
    result = parse_worker_result("")
    assert isinstance(result, UntrustedResult)


def test_multiple_blocks_returns_untrusted():
    block = (
        "<ralph-result>\n"
        "status: done\nsummary: x\nverification: y\ncomplete: true\nblocker: none\n"
        "</ralph-result>"
    )
    result = parse_worker_result(block + "\n" + block)
    assert isinstance(result, UntrustedResult)
    assert "multiple" in result.reason


# ---------------------------------------------------------------------------
# Failure paths — missing required fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", ["status", "summary", "verification", "complete", "blocker"])
def test_missing_required_field_returns_untrusted(missing_field: str):
    fields = {
        "status": "done",
        "summary": "did it",
        "verification": "checked",
        "complete": "true",
        "blocker": "none",
    }
    del fields[missing_field]
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    output = f"<ralph-result>\n{body}\n</ralph-result>"
    result = parse_worker_result(output)
    assert isinstance(result, UntrustedResult)
    assert missing_field in result.reason


# ---------------------------------------------------------------------------
# Failure paths — invalid field values
# ---------------------------------------------------------------------------


def test_invalid_status_returns_untrusted():
    result = parse_worker_result(_make_block(status="ok"))
    assert isinstance(result, UntrustedResult)
    assert "invalid status" in result.reason


def test_invalid_complete_value_returns_untrusted():
    result = parse_worker_result(_make_block(complete="yes"))
    assert isinstance(result, UntrustedResult)
    assert "invalid complete value" in result.reason


def test_complete_true_with_non_done_status_returns_untrusted():
    """complete=true is only valid when status=done."""
    result = parse_worker_result(_make_block(status="partial", complete="true"))
    assert isinstance(result, UntrustedResult)
    assert "complete=true" in result.reason


def test_empty_summary_returns_untrusted():
    result = parse_worker_result(_make_block(summary=""))
    assert isinstance(result, UntrustedResult)
    assert "summary" in result.reason


def test_empty_verification_returns_untrusted():
    result = parse_worker_result(_make_block(verification=""))
    assert isinstance(result, UntrustedResult)
    assert "verification" in result.reason


# ---------------------------------------------------------------------------
# UntrustedResult interface
# ---------------------------------------------------------------------------


def test_untrusted_result_interface():
    """UntrustedResult must expose the same property names as WorkerResultBlock."""
    u = UntrustedResult(raw_stdout="x", reason="test")
    assert u.is_trusted is False
    assert u.complete is False
    assert u.status == "untrusted"
    assert u.summary == ""
    assert u.verification == ""
    assert u.blocker == "test"
    assert u.completion_confidence == "unverified"


# ---------------------------------------------------------------------------
# No fake success guarantee
# ---------------------------------------------------------------------------


def test_untrusted_result_complete_is_always_false():
    """Callers must not be able to treat UntrustedResult as successful."""
    for stdout in ["", "garbage", "status: done\ncomplete: true (no block tags)"]:
        result = parse_worker_result(stdout)
        if isinstance(result, UntrustedResult):
            assert result.complete is False, (
                f"UntrustedResult.complete must be False, got True for input: {stdout!r}"
            )
