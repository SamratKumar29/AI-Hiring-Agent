# Handoff - continue on another computer

Status (2026-10-14): Phases 0-9 are built and tested (342 tests). What is left is **verification that needs a real network**:
Telegram, the Resume-Matcher PDF on an unrestricted connection, and the live half of the UI acceptance (plan.md step 9.15).
`plan.md` is the full build plan and progress log; `README.md` explains how to use the project.

## 1. Set up the new machine (about 15 minutes)

```bash
git clone https://github.com/SamratKumar29/AI-Hiring-Agent.git && cd AI-Hiring-Agent
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
nvm install 22
(cd career-ops && npm install && npx playwright install chromium)
cp brain/.env.example brain/.env && chmod 600 brain/.env      # then fill in the keys, see below
# optional second CV engine (Resume-Matcher):
(cd Resume-Matcher/apps/backend && uv sync --python 3.13 && .venv/bin/python -m playwright install chromium-headless-shell)
(cd Resume-Matcher/apps/frontend && npm install --legacy-peer-deps)
./venv/bin/python hire.py doctor          # every line should be PASS or an explained WARN
./venv/bin/pytest -q                      # 342 pass
```

## 2. What did NOT come through git (copy or recreate)

| Item | How |
|---|---|
| `brain/.env` (OpenRouter key, models, Telegram, Firecrawl...) | copy the file, or paste the keys again. Check `chmod 600` afterwards |
| Your real CV (`Samrat_Kumar_Resume_Master.md`) and profile | git-ignored on purpose. Copy `career-ops/profile/<name>/` or use the UI: *Logs & Maintenance > Export / Import* |
| Run logs, caches (`brain/data/`) | not needed |

Note: the real CV was committed once in the early history of the public repo (`fa16d6a`, branch `v1.0`), so its contact details are
visible in old commits. Removing it from history needs a history rewrite + force push - decide that separately.

## 3. Your checklist

1. **Telegram**: `./venv/bin/python hire.py notify setup`, then `notify test`. (Blocked on the office proxy; works elsewhere.)
   If you must use a network with TLS interception, point `REQUESTS_CA_BUNDLE` at the company CA file.
2. **Resume-Matcher PDF**: `hire.py tailor <job> --engine resume-matcher` (needs the optional setup above; first run builds its
   frontend once). Self-hosted fonts are already patched in (`patches/resume-matcher/`).
3. **UI acceptance (9.15)**: `./start_ui.sh` then walk through Goals 3-7 in the browser: Discover, Rank, like a job, build a CV
   with both engines, cover letter + interview prep. Goals 1, 2, 8, 9 were already verified.
4. **Schedule**: Schedule page > *Install*, or `hire.py schedule install` (time comes from `DAILY_TIME=20:00`). Add `--windows`
   if WSL is often closed. Then confirm the first Telegram digest arrives.
5. **Models**: put your final OpenRouter model order in *Setup > Models*. Free models can be slow (one job took 44 minutes);
   a fast model first makes daily runs quick. `MAX_EVALS_PER_RUN` (20) and `MONTHLY_SPEND_LIMIT_USD` (5) guard cost.
6. **Real profile**: the saved `samrat` profile is a basic test profile (roles "AI related roles", location "Any"). Create a
   proper one (Profiles page) before relying on the daily digest.

## 4. Known limits and gotchas

- Behind an office proxy Node ignores proxy settings unless `NODE_USE_ENV_PROXY=1`; the agent sets it automatically when a proxy
  variable exists (cron has none - fine on a normal network).
- Resume-Matcher needs a model that answers in strict JSON (`RESUME_MATCHER_MODELS`, default `xiaomi/mimo-v2.6-flash`).
  The built-in career-ops engine works with any model.
- Naukri, Indeed and Multi Recruit pages cannot be scraped; they are reported as "not scrapable", never faked.
- The career-ops test suite (`cd career-ops && node test-all.mjs`) has ~17 environment-related failures; see plan.md Phase 8.
- Cron only runs while the computer/WSL is awake.

## 5. If you hand this to another AI model

Read `plan.md` first (Sections 5 and 6: rules and the dated Progress Log), then `README.md`. Logic lives in `brain/`; `hire.py`
and `ui/` are thin wrappers. Run `hire.py doctor` and `pytest -q` before changing anything, and `pytest -q` after.
