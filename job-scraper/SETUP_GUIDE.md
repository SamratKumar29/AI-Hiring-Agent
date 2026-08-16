# Your job-search agent — setup guide

This is a fork of [anandanair/job-scraper](https://github.com/anandanair/job-scraper) with two additions:

1. **`evaluate_job.py`** — give it a URL, a local PDF, or pasted text, and it scores
   the role against your resume + your minimum salary threshold, then tells you
   Strong match / Worth applying / Borderline / Skip, with reasons.
2. **`.github/workflows/evaluate_job.yml`** — lets you run that evaluator by hand
   from the GitHub Actions tab (works from the GitHub mobile app too), so you
   don't need your own server for the "check this link/PDF" use case.

The original repo already runs 24×7-ish for free via **GitHub Actions** on a
daily cron (`scrape_jobs.yml`, `score_jobs.yml`, etc.) — that satisfies your
"free cloud" requirement without renting a VM. GitHub Actions gives free
private-repo minutes (2,000/month on the free tier), which is enough for
daily scraping + scoring runs.

## 1. Make it yours (10 min)

1. Fork this repo (or push this folder to a new GitHub repo of your own).
2. Sign up for free tiers:
   - **Supabase** (https://supabase.com) — free Postgres DB for storing jobs.
     Run `supabase_setup/init.sql` in the Supabase SQL editor once.
   - **Gemini API key** (https://aistudio.google.com/apikey) — free tier is
     generous and is the repo's default LLM. (Or any LiteLLM-supported
     provider — OpenAI, Groq, Anthropic, etc. — set `LLM_MODEL` in
     `config.py` accordingly.)
3. In your GitHub repo, go to **Settings → Secrets and variables → Actions**
   and add:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `GEMINI_API_KEY` (or `LLM_API_KEY` for other providers)
4. Add your resume: run `python resume_parser.py` locally once (or trigger
   the `parse_resume.yml` workflow) pointed at your resume PDF — it produces
   `resume.json`, which everything else scores against.

## 2. Set your preferences

Edit `config.py`:

- `MIN_SALARY_USD` — your salary threshold. Roles below this get flagged.
- `REMOTE_ONLY` — set `True` if you only want remote roles.
- `LINKEDIN_SEARCH_QUERIES` — your target job titles.
- `LINKEDIN_F_WT` — `2` for remote-only search, `1` onsite, `3` hybrid.
- `LINKEDIN_LOCATION` / `LINKEDIN_GEO_ID` — target market (worldwide by
  default now).

For sources beyond LinkedIn: the repo's `scraper.py` also supports Singapore's
"MyCareersFuture" out of the box. Adding another board (Indeed, Wellfound,
RemoteOK, WeWorkRemotely) means adding a new scraping function following the
same pattern as the existing ones in `scraper.py` — happy to build one out
with you for a specific board once you pick which matters most (LinkedIn +
one remote-specific board covers most of the "remote jobs" surface area
already, since remote boards often just re-list the same postings).

## 3. Turn on the 24×7 schedule

The workflows already exist and default to daily crons:

- `scrape_jobs.yml` — pulls new postings.
- `score_jobs.yml` — scores them against `resume.json`.
- `job_manager.yml` — housekeeping (expiry, dedup).

They run automatically once secrets are set — no server needed. Adjust the
`cron:` line in each workflow file to run more/less often (GitHub Actions
free tier: keep total runtime reasonable — daily runs are well within the
free 2,000 min/month).

## 4. Evaluate a specific link or PDF

**From your computer:**
```bash
python evaluate_job.py --url "https://company.com/careers/123"
python evaluate_job.py --pdf "~/Downloads/job_description.pdf"
```

**From your phone, no computer needed:**
Go to your repo → Actions tab → "Evaluate a Job Posting" → Run workflow →
paste the URL or job text → Run. Check the log a minute later for the
verdict (or download the `evaluated-jobs` artifact, which accumulates a
running history in `evaluated_jobs.jsonl`).

## Notes on LinkedIn/Indeed/Glassdoor scraping

These sites actively block scrapers and change their markup often — that's
why the base repo scrapes LinkedIn's public job-search JSON endpoint rather
than the site itself, and why heavily JS-rendered sites (Indeed, Glassdoor)
are harder to add reliably. If a scraper breaks, it's usually a selector/
endpoint change on their end, not a bug in your setup — check the repo's
issues page or the site's current search URL structure.
