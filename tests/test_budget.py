from brain import budget, config, prep, rank


def _use(monkeypatch, monthly=0.0, remaining=None, ok=True):
    monkeypatch.setattr(budget, "usage", lambda: {"ok": ok, "monthly": monthly, "limit_remaining": remaining, "error": None if ok else "boom"})


def test_defaults(monkeypatch):
    monkeypatch.delenv("MAX_EVALS_PER_RUN", raising=False)
    monkeypatch.delenv("MONTHLY_SPEND_LIMIT_USD", raising=False)
    assert budget.max_evals() == 20 and budget.monthly_limit() == 5.0


def test_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv("MAX_EVALS_PER_RUN", "lots")
    monkeypatch.setenv("MONTHLY_SPEND_LIMIT_USD", "x")
    assert budget.max_evals() == 20 and budget.monthly_limit() == 5.0


def test_under_limit_allowed(monkeypatch):
    monkeypatch.setenv("MONTHLY_SPEND_LIMIT_USD", "5")
    _use(monkeypatch, monthly=1.2)
    assert budget.check()["allowed"]
    budget.require()


def test_over_limit_blocks_with_clear_reason(monkeypatch):
    monkeypatch.setenv("MONTHLY_SPEND_LIMIT_USD", "5")
    _use(monkeypatch, monthly=5.0)
    c = budget.check()
    assert not c["allowed"] and "MONTHLY_SPEND_LIMIT_USD" in c["reason"]
    try:
        budget.require()
        assert False
    except budget.BudgetExceeded as e:
        assert "protect your credits" in str(e)


def test_zero_limit_disables_guard(monkeypatch):
    monkeypatch.setenv("MONTHLY_SPEND_LIMIT_USD", "0")
    _use(monkeypatch, monthly=999)
    assert budget.check()["allowed"]


def test_key_credit_exhausted_blocks(monkeypatch):
    monkeypatch.setenv("MONTHLY_SPEND_LIMIT_USD", "0")
    _use(monkeypatch, monthly=1, remaining=0)
    assert not budget.check()["allowed"]


def test_unreadable_usage_fails_open(monkeypatch):
    _use(monkeypatch, ok=False)
    c = budget.check()
    assert c["allowed"] and "not checked" in c["reason"]


def test_usage_never_raises_on_network_error(monkeypatch):
    import requests
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    assert budget.usage()["ok"] is False


def test_rank_aborts_over_budget(active, monkeypatch):
    monkeypatch.setenv("MONTHLY_SPEND_LIMIT_USD", "1")
    _use(monkeypatch, monthly=2)
    try:
        rank.run(active)
        assert False
    except budget.BudgetExceeded:
        pass


def test_prep_refuses_over_budget(active, monkeypatch):
    monkeypatch.setenv("MONTHLY_SPEND_LIMIT_USD", "1")
    _use(monkeypatch, monthly=2)
    r = prep.generate("whatever", "cover", active)
    assert not r["ok"] and "credits" in r["error"]
