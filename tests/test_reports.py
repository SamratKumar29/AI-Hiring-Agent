from brain import reports
from tests.report_samples import TOOL_CALL, report


def test_full_report_with_machine_summary():
    r = reports.parse(report())
    assert r["ok"] and r["score"] == 4.2 and r["legitimacy"] == "High Confidence" and r["final_decision"] == "Apply"
    assert r["top_strengths"] == ["RAG"] and r["soft_gaps"] == ["no cloud"] and r["hard_stops"] == []
    assert r["advertised_comp"] == "Rs 20-30 LPA" and r["url"] == "https://x.com/jobs/1" and r["blocks"] == 7


def test_free_models_often_skip_the_fence_header_is_enough():
    r = reports.parse(report(fence=False))
    assert r["ok"] and r["score"] == 4.2 and r["legitimacy"] == "High Confidence" and "no machine summary" in r["problems"]


def test_tool_call_text_is_rejected():
    r = reports.parse(TOOL_CALL)
    assert not r["ok"] and r["score"] is None and any("score" in p for p in r["problems"])


def test_rejects_short_and_out_of_range_scores():
    assert not reports.parse("**Score:** 4.0/5\nshort")["ok"]
    assert not reports.parse(report(score="9.5"))["ok"] and not reports.parse(report(score="0"))["ok"]


def test_score_variants_and_bad_yaml():
    assert reports.parse(report(score="3"))["score"] == 3.0
    broken = report(extra_ms="  bad: [unclosed\n")
    r = reports.parse(broken)
    assert r["score"] == 4.2 and any("YAML" in p for p in r["problems"])


def test_pasted_text_url_header_variants():
    assert reports.parse(report(url="(pasted)"))["url"] == "(pasted)"
    assert reports.report_number("career-ops/reports/012-acme-2026-10-12.md") == 12
    assert reports.report_number("weird.md") is None
