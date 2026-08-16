# Job Search Agent — Combined Setup Guide

This folder combines 4 open-source repos into one job-search pipeline. This
file is written to be handed to an AI coding CLI (Claude Code, Cline,
Antigravity) to execute. It assumes the repos are already cloned as sibling
folders here:

```
job-agent-project/
├── career-ops/              (santifer/career-ops — the central brain)
├── job-scraper/             (anandanair/job-scraper — local, on-demand LinkedIn discovery)
├── ai-job-scraper/           (Kurt-Chan/ai-job-scraper — scheduled multi-board discovery)
├── Resume-Matcher/          (srbhr/Resume-Matcher — alt CV tailoring, optional 2nd opinion)
├── integration/              (glue scripts — provided, see below)
│   ├── 00_shared_jobs_table_migration.sql
│   ├── kurt_chan_supabase_sync.py
│   └── sync-pipeline.mjs
└── AGENT_SETUP.md            (this file)
```

## How the pieces fit together

```
                         ┌─────────────────────────────┐
                         │   Supabase "jobs" table      │
                         │  (shared discovery inbox)    │
                         └──────────────┬───────────────┘
                    ▲                   │
     writes         │                   │ sync-pipeline.mjs reads
     ┌───────────────┴──────────┐       │ unsynced rows, appends to
     │                          │       ▼
┌────┴─────┐            ┌───────┴──────────┐    ┌──────────────────────┐
│anandanair│            │  Kurt-Chan        │    │ career-ops           │
│job-scraper│           │  ai-job-scraper   │    │ data/pipeline.md     │
│(local,    │           │  (scheduled via   │    │ (URL inbox)          │
│ manual    │           │   GitHub Actions) │    └──────────┬───────────┘
│ "hit start│           └───────────────────┘               │
│  ")       │                                     /career-ops pipeline
└───────────┘                                                │
                                                              ▼
                                             ┌──────────────────────────────┐
                                             │ career-ops evaluation (A-F)   │
                                             │ ranks by fit + your profile   │
                                             │ (LLM: OpenRouter via          │
                                             │  openai-eval.mjs)             │
                                             └──────────────┬────────────────┘
                                                             │ you review, pick roles you like
                                                             ▼
                              ┌──────────────────────────────────────────┐
                              │ Dual CV generation for chosen role:        │
                              │  A) career-ops built-in generator          │
                              │  B) Resume-Matcher tailoring                │
                              │  → you pick the better of the two          │
                              └──────────────────┬───────────────────────┘
                                                  ▼
                              cover letter, interview prep, offer prep
                              (career-ops modes: cover.md, interview-prep.md,
                               offer-prep.md — run as needed, per application)
```

## Step-by-step setup

### 1. Supabase (shared discovery store — free tier)
1. Create a free project at supabase.com.
2. In the SQL editor, run `job-scraper/supabase_setup/init.sql` (creates the base `jobs` table).
3. Then run `integration/00_shared_jobs_table_migration.sql` (adds `job_url`, `source`, `salary_text`, `synced_to_pipeline` columns — makes the table a shared inbox for both scrapers).
4. Note your `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

### 2. career-ops (central brain) — run locally
1. `cd career-ops && npm install` (check `package.json` for exact install command — it's a script collection, not a build step, so this may be minimal).
2. Copy `config/profile.example.yml` → `config/profile.yml` and fill in identity, target roles, comp range, `MIN_SALARY_USD`-equivalent (career-ops calls this comp range in `profile.yml`).
3. Run intake: open this folder in Claude Code / Cline and run `/career-ops intake` — point it at your existing resume/CV.md (or a master resume file, LinkedIn export, etc. dropped in `documents/`). This builds `cv.md`, `modes/_profile.md`, `modes/_brief.md` — your permanent profile.
4. Set the LLM: for OpenRouter, no code change needed — `openai-eval.mjs` (used for headless/scripted evaluation) already supports it:
   ```bash
   export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
   export OPENAI_API_KEY="<your-openrouter-key>"
   export OPENAI_MODEL="<model-id, e.g. anthropic/claude-sonnet-4>"
   ```
   If you're running interactively inside Claude Code/Cline instead, career-ops just uses whatever LLM is driving that CLI session — no extra config needed there.
5. Copy `integration/sync-pipeline.mjs` into the `career-ops/` folder root. Install its one dependency: `npm install @supabase/supabase-js`. Put `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` in a local `.env` (gitignored).

### 3. anandanair/job-scraper (local, on-demand LinkedIn)
1. `cd job-scraper && pip install -r requirements.txt --break-system-packages`
2. Fill in `config.py`: `LINKEDIN_SEARCH_QUERIES`, `LINKEDIN_LOCATION`, `MIN_SALARY_USD`, `REMOTE_ONLY` — use the version from your earlier zip (already has these + `evaluate_job.py`, keep it).
3. Add `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `LLM_API_KEY` (or `GEMINI_API_KEY`) to a local `.env`.
4. When you want to search: `python scraper.py` then `python score_jobs.py`. Results land straight in the shared Supabase `jobs` table — no extra glue needed here, it already writes to the same table the migration extended.

### 4. Kurt-Chan/ai-job-scraper (scheduled, multi-board)
1. `cd ai-job-scraper`, edit `config.json` — set `job_boards` to the ones you want (LinkedIn/Indeed/Wellfound/Glassdoor/JobStreet/OnlineJobs.ph) and your Reddit subreddits, or trim to just the ones not already covered by career-ops's own `scan.mjs` (Greenhouse/Ashby/Lever etc.) to avoid duplicate evaluation work.
2. Copy `integration/kurt_chan_supabase_sync.py` into this folder.
3. Add `pip install supabase` to its requirements.
4. Set up a GitHub Actions workflow (same pattern as `job-scraper/.github/workflows/scrape_jobs.yml`) that runs `python agent.py` then `python kurt_chan_supabase_sync.py` on a schedule, with `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` as repo secrets. This is your 24×7 piece — free, no server.

### 5. Resume-Matcher (optional 2nd CV path)
1. Follow `Resume-Matcher/SETUP.md` as-is (it's a full local web app: FastAPI backend + Next.js frontend, its own local DB — separate from the Supabase jobs table, by design, since it's CV-tailoring, not job discovery).
2. Run it locally when you want a second tailored CV: feed it your `cv.md` + the JD text from the career-ops report you're applying to.

### 6. Daily / on-demand loop
1. **Discovery**: Kurt-Chan runs on schedule automatically. When you want LinkedIn results too, run `job-scraper/scraper.py` locally.
2. **Sync**: `cd career-ops && node sync-pipeline.mjs` — pulls everything new from Supabase into `data/pipeline.md`.
3. **Evaluate + rank**: in Claude Code/Cline, run `/career-ops pipeline` — scores everything against your profile, writes reports, updates the tracker.
4. **Review**: check `data/applications.md` / the dashboard (`career-ops/dashboard`) for ranked results, open the original postings for ones you like.
5. **Tailor**: for a role you want to apply to, generate CV A (`/career-ops` CV/apply mode) and CV B (Resume-Matcher, manual), compare, pick one.
6. **Apply support**: `/career-ops cover` for the cover letter, `/career-ops interview-prep` once you have an interview, `/career-ops offer-prep` if you get an offer.

### 7. One-off link/PDF check (no scraping needed)
Drop a single URL straight into `career-ops/data/pipeline.md` under `## Pending` yourself, or use `job-scraper/evaluate_job.py --url "..."` for a quick standalone score — both work independently of the scheduled pipeline.

## Open items to decide as you go
- **Naukri / Michael Page / Multi-Recruit**: none of the 4 repos scrape these today. Lowest-effort path: add a new provider module to career-ops's `providers/` (it has ~40 existing ones as templates) or a new board function in Kurt-Chan's `agent.py`. Worth doing once the core loop above is working end-to-end.
- **Dedup across sources**: career-ops's `dedup-tracker.mjs` / `detect-reposts.mjs` already catch cross-listed postings once they're in the pipeline — no extra work needed there.
