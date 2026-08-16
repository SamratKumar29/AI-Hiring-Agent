-- Run this once in your Supabase SQL editor, AFTER running
-- job-scraper (anandanair)/supabase_setup/init.sql (which creates the base "jobs" table).
--
-- It extends that table into a shared discovery store that BOTH scrapers
-- (anandanair/job-scraper and Kurt-Chan/ai-job-scraper) write into, and that
-- career-ops's pipeline sync script reads from.
--
-- Idempotent: safe to run multiple times.

ALTER TABLE "public"."jobs"
  ADD COLUMN IF NOT EXISTS "job_url" text,
  ADD COLUMN IF NOT EXISTS "source" text DEFAULT 'linkedin_anandanair',
  ADD COLUMN IF NOT EXISTS "salary_text" text,
  ADD COLUMN IF NOT EXISTS "synced_to_pipeline" boolean DEFAULT false;

-- job_url must be unique so both scrapers can upsert without creating dupes
-- when the same posting is found by two sources.
CREATE UNIQUE INDEX IF NOT EXISTS jobs_job_url_key ON "public"."jobs" ("job_url")
  WHERE "job_url" IS NOT NULL;

-- Fast lookup for career-ops's pipeline sync script.
CREATE INDEX IF NOT EXISTS jobs_synced_to_pipeline_idx ON "public"."jobs" ("synced_to_pipeline")
  WHERE "synced_to_pipeline" = false;

COMMENT ON COLUMN "public"."jobs"."job_url" IS 'Canonical posting URL — required for non-LinkedIn sources (Kurt-Chan scraper), optional for LinkedIn rows which can be derived from job_id';
COMMENT ON COLUMN "public"."jobs"."source" IS 'Which scraper found this: linkedin_anandanair | indeed_kurtchan | wellfound_kurtchan | glassdoor_kurtchan | jobstreet_kurtchan | reddit_kurtchan | manual';
COMMENT ON COLUMN "public"."jobs"."salary_text" IS 'Raw salary/comp string as posted, if any (career-ops pipeline.md format wants this)';
COMMENT ON COLUMN "public"."jobs"."synced_to_pipeline" IS 'Whether this row has already been appended to career-ops data/pipeline.md — set true by sync-pipeline.mjs';
