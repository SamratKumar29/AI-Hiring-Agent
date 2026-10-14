# AI Hiring Agent

A personal job-hunting agent that runs on your own machine. It learns your profile from your CV, finds jobs on the boards
you choose, ranks them by fit, tailors a CV for the ones you like, and then helps with the cover letter, interview and
offer preparation. One daily run can send you the best matches on Telegram.

Built from: [career-ops](career-ops/) (ranking, reports, CV maker, prep modes), [Resume-Matcher](Resume-Matcher/)
(second CV tailoring engine), [ai-job-scraper](ai-job-scraper/) (scheduled discovery) and [job-scraper](job-scraper/)
(manual LinkedIn discovery). One "brain" (`brain/`) ties them together and talks to one LLM provider (OpenRouter).

Everything stays local: your profile, jobs database, reports and PDFs live in `career-ops/profile/<name>/`
(git-ignored). The only data sent out are the prompts to OpenRouter and optional Firecrawl/Telegram calls.

## Setup (once)

Needs: git, Python 3.12+, Node.js 22+ (`nvm install 22`), and for the optional Resume-Matcher engine `uv` (`pip install uv`) with Python 3.13.
Works on Linux, macOS and WSL2 (Windows: run everything inside WSL; native Windows is untested).

```bash
git clone https://github.com/SamratKumar29/AI-Hiring-Agent.git && cd AI-Hiring-Agent
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
(cd career-ops && npm install && npx playwright install chromium)      # ranking engine + built-in CV maker (PDF)
# if "npm install" stops at its Chromium step: npm install --ignore-scripts, then npx playwright install chromium
cp brain/.env.example brain/.env && chmod 600 brain/.env              # then edit it (next section)
```

Optional second CV engine, Resume-Matcher (the code is in the repo; its dependencies are not):

```bash
(cd Resume-Matcher/apps/backend && uv sync --python 3.13 && .venv/bin/python -m playwright install chromium-headless-shell)
(cd Resume-Matcher/apps/frontend && npm install --legacy-peer-deps)   # its first PDF export builds the frontend once (~2 min)
```

On a fresh Linux/WSL install Chromium may need system libraries: `sudo npx playwright install-deps chromium`.

Edit `brain/.env` (the only place with secrets):

| Setting | Meaning |
|---|---|
| `OPENROUTER_API_KEY` | required, one key for everything |
| `OPENROUTER_MODELS` / `OPENROUTER_PAID_FALLBACK` | models in priority order; free first, paid only when all free fail |
| `FIRECRAWL_API_KEY` | optional, fetches full job texts |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional, set by `hire.py notify setup` |
| `DAILY_TIME` | daily run time, e.g. `20:00` |
| `MAX_EVALS_PER_RUN` | most jobs ranked per run (default 20) |
| `MONTHLY_SPEND_LIMIT_USD` | stop ranking/writing when this month's OpenRouter spend reaches it (default 5, `0` = off) |
| `RESUME_MATCHER_MODELS` | models Resume-Matcher tries first (it needs strict JSON output) |

Then check everything with one command:

```bash
./venv/bin/python hire.py doctor          # PASS / WARN / FAIL list with a fix for each problem
./venv/bin/python hire.py doctor --llm    # also makes one real model call
```

Optional PDF engine (Resume-Matcher): see [patches/resume-matcher/README.md](patches/resume-matcher/README.md) (self-hosted
fonts, so no Google Fonts access is needed) and run
`Resume-Matcher/apps/backend/.venv/bin/python -m playwright install chromium-headless-shell` once.

## Web interface (everything in the browser)

```bash
./start_ui.sh            # or: ./venv/bin/python hire.py ui      (Windows: double-click AI-Hiring-Agent.bat)
```

Opens http://localhost:8501. Pages: **Home** (status, top jobs, needs-attention list, spend) - **Setup** (API key, model order,
Telegram/email, settings, doctor) - **Profiles** (create from a CV, edit, duplicate, delete/restore) - **Sources** (links, PDFs,
board quick-add) - **Run** (discover, rank, full daily run with live progress and history) - **Jobs** (filter, like/dismiss/applied,
reports, notes) - **Resume Builder** (career-ops / Resume-Matcher / both, PDF preview) - **Application Prep** (cover letter,
interview, offer, follow-up, outreach) - **Schedule** (install the daily run, run now, digests) - **Logs & Maintenance**
(run logs, backups, trash, export/import). Runs started from the command line or by cron appear in the same history.

## Everyday use (command line)

All commands: `./venv/bin/python hire.py <command>` (`--help` on any command).

| Step | Command |
|---|---|
| 1. Create a profile from your CV (asks your preferences and minimum salary) | `profile create --resume cv.md` |
| &nbsp;&nbsp;&nbsp;load / edit / list / delete | `profile activate NAME`, `profile edit NAME`, `profile list`, `profile delete NAME --yes` (recoverable via `profile restore`) |
| 2. Add job sources: board search links, single postings, company pages, a PDF/text file of links | `sources add <url or file>`; `sources list` |
| 3. Find jobs now (scheduled scrapers + boards) / also LinkedIn (slow) | `discover` / `discover --manual` |
| 4. Rank them against your profile | `rank` (`--max N`) |
| 5. See the best ones, open one in the browser | `show`, `show --open 3` |
| 6. Tailored CV (PDF) | `tailor 3` (career-ops) / `tailor 3 --engine resume-matcher` / `tailor 3 --engine both` |
| 7. After applying: cover letter, interview prep, offer prep, follow-up, outreach | `prep 3` (menu) or `prep 3 --kind cover`; `prep 3 --kind applied` marks it applied |

`3` is the report number shown by `show`; a job id or posting URL also works. Outputs: `career-ops/profile/<name>/workspace/output/`
(`resumes/<job>/`, `prep/<job>/`, `digests/`).

## Daily run and notifications

```bash
./venv/bin/python hire.py notify setup        # guided Telegram bot setup (needs internet access to api.telegram.org)
./venv/bin/python hire.py notify test
./venv/bin/python hire.py daily               # discover -> rank -> digest -> Telegram (what the schedule runs)
./venv/bin/python hire.py daily --no-send     # same, without sending
./venv/bin/python hire.py schedule install    # every day at DAILY_TIME (cron); add --windows for Windows Task Scheduler
./venv/bin/python hire.py schedule status
./venv/bin/python hire.py schedule remove
```

Before every run the agent checks that OpenRouter answers and falls back through the model list; if no model works it tells
you and tries again at the next run. If no channel is configured, results are only saved locally (`hire.py show`).
Cron only runs while WSL / the computer is awake - use `--windows` to also catch up after a missed start.

## Cost safety

- At most `MAX_EVALS_PER_RUN` jobs are ranked per run; the monthly guard stops `rank`, `daily`, `tailor` and `prep` when
  OpenRouter reports spend above `MONTHLY_SPEND_LIMIT_USD` (or the key's own credit limit is used up).
- Free models can be slow or rate-limited; a run with only free models can take a long time. Put a fast model first in
  `OPENROUTER_MODELS` if you want quick runs.

## Layout

```
brain/            the shared logic (profiles, discovery, ranking, notifications, scheduling, tailoring, prep, doctor, task runner)
hire.py           command line (thin wrapper over brain/)
ui/               web interface (Streamlit pages; they only call brain/)
career-ops/       ranking engine, report/CV modes; career-ops/profile/<name>/ holds YOUR files (git-ignored)
Resume-Matcher/   optional second CV engine (started on demand on ports 8765/8766)
ai-job-scraper/, job-scraper/   discovery sources
patches/          local patches applied to third-party code
tests/            ./venv/bin/pytest -q   (mocks; add -m live for real API calls)
plan.md           build plan and progress log (resume point for any model)
```

## Moving to another computer

Git carries the code only. These are deliberately **not** in the repository and must be recreated or copied by hand:
`brain/.env` (all keys), your real CV and profile (`career-ops/profile/<name>/` - copy the folder, or use *Logs & Maintenance >
Export / Import*), `brain/data/` (run logs, caches), and the installed dependencies (`venv/`, `node_modules/`, Resume-Matcher's
`.venv`). After setup run `hire.py doctor`. See [Handoff.md](Handoff.md) for the current checklist.

## Tests

```bash
./venv/bin/pytest -q                      # unit + integration + web-UI tests with mocks (uses the fictional CV in tests/fixtures)
./venv/bin/pytest -q -m live              # real OpenRouter calls
(cd career-ops && node test-all.mjs)      # upstream career-ops suite
```

Known environment-only failures of the career-ops suite: tests that need live internet (archive-posting, resolver outage),
tests that assume `output/` is a real folder (this project symlinks it into the active profile) and a missing Go dashboard
data folder.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Telegram: `CERTIFICATE_VERIFY_FAILED` | an office proxy is intercepting TLS; use another network or set `REQUESTS_CA_BUNDLE` to your company CA file |
| No model answers | free models are rate-limited; `./venv/bin/python -m brain.health --select`, add a paid fallback |
| Resume-Matcher fails but career-ops works | the model cannot produce strict JSON; set `RESUME_MATCHER_MODELS` |
| `Stopped to protect your credits` | raise `MONTHLY_SPEND_LIMIT_USD` or set it to `0` |
| Anything else | `hire.py doctor` |

## Migrating from the old Supabase setup

The Supabase sync (`integration/`) was replaced by the local database and is no longer used. `AGENT_SETUP.md` is kept
only as history. Remove `integration/` yourself when you are sure you do not need it.

## License

MIT - see the individual subproject licenses.
