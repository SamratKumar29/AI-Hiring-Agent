import pytest

from brain import health


@pytest.mark.live
def test_openrouter_is_reachable_and_a_model_answers():
    r = health.check()
    assert r["ok"], f"OpenRouter not healthy: {r['error']}"


@pytest.mark.live
def test_model_selection_finds_a_working_model():
    from brain import llm

    seen = []
    sel = llm.select_model(force=True, on_result=seen.append)
    for r in seen:
        print(f"[{r['tier']}] {'OK' if r['ok'] else 'FAIL'} {r['model']} {r['error'] or ''}")
    assert sel["model"] and sel["tier"] in ("free", "paid")
