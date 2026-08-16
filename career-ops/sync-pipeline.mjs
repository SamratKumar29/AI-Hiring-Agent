#!/usr/bin/env node
/**
 * sync-pipeline.mjs
 *
 * Pulls jobs discovered by anandanair/job-scraper (local, on-demand) and
 * Kurt-Chan/ai-job-scraper (scheduled, GitHub Actions) out of the shared
 * Supabase "jobs" table and appends them to career-ops's data/pipeline.md
 * URL inbox, in the format career-ops's own modes/pipeline.md expects:
 *
 *   - [ ] {url} | {company} | {role} | {location} | {salary}
 *
 * Run this from the career-ops project root, THEN run `/career-ops pipeline`
 * (in Claude Code / Cline / whatever CLI you're using) to evaluate everything
 * that landed in the inbox.
 *
 * Usage:
 *   node sync-pipeline.mjs
 *
 * Requires env vars (put them in a local .env, gitignored):
 *   SUPABASE_URL
 *   SUPABASE_SERVICE_ROLE_KEY
 */

import { createClient } from '@supabase/supabase-js';
import { readFileSync, writeFileSync, existsSync } from 'fs';

const PIPELINE_PATH = 'data/pipeline.md';
const MIN_SCORE_TO_INCLUDE = 0; // set >0 to only pull jobs already pre-scored highly by the scrapers

function requireEnv(name) {
  const v = process.env[name];
  if (!v) {
    console.error(`Missing required env var: ${name}`);
    process.exit(1);
  }
  return v;
}

function loadPipeline() {
  if (!existsSync(PIPELINE_PATH)) {
    return '## Pending\n\n## Processed\n';
  }
  return readFileSync(PIPELINE_PATH, 'utf-8');
}

function appendToPending(content, newLines) {
  const marker = '## Pending';
  const idx = content.indexOf(marker);
  if (idx === -1) {
    // No existing structure — create it.
    return `## Pending\n${newLines.join('\n')}\n\n## Processed\n` + content;
  }
  // Find end of the "## Pending" section (next "## " heading, or end of file).
  const afterMarker = idx + marker.length;
  const nextHeadingIdx = content.indexOf('\n## ', afterMarker);
  const insertAt = nextHeadingIdx === -1 ? content.length : nextHeadingIdx;
  return (
    content.slice(0, insertAt) +
    '\n' + newLines.join('\n') +
    content.slice(insertAt)
  );
}

function toPipelineLine(job) {
  const url = job.job_url || (job.job_id?.match(/^\d+$/) ? `https://www.linkedin.com/jobs/view/${job.job_id}` : null);
  if (!url) return null;

  const parts = [url, job.company || 'Unknown', job.job_title || 'Unknown'];
  if (job.location) parts.push(job.location);
  if (job.salary_text) parts.push(job.salary_text);

  return `- [ ] ${parts.join(' | ')}`;
}

async function main() {
  const supabaseUrl = requireEnv('SUPABASE_URL');
  const supabaseKey = requireEnv('SUPABASE_SERVICE_ROLE_KEY');
  const supabase = createClient(supabaseUrl, supabaseKey);

  let query = supabase
    .from('jobs')
    .select('job_id, job_url, company, job_title, location, salary_text, resume_score')
    .eq('synced_to_pipeline', false)
    .eq('is_active', true);

  if (MIN_SCORE_TO_INCLUDE > 0) {
    query = query.gte('resume_score', MIN_SCORE_TO_INCLUDE);
  }

  const { data: jobs, error } = await query;

  if (error) {
    console.error('Supabase query failed:', error.message);
    process.exit(1);
  }

  if (!jobs || jobs.length === 0) {
    console.log('No new jobs to sync — pipeline.md already up to date.');
    return;
  }

  const lines = [];
  const syncedIds = [];
  for (const job of jobs) {
    const line = toPipelineLine(job);
    if (line) {
      lines.push(line);
      syncedIds.push(job.job_id);
    } else {
      console.warn(`Skipping job with no derivable URL: ${job.company} / ${job.job_title}`);
    }
  }

  if (lines.length === 0) {
    console.log('No syncable jobs (all missing URLs).');
    return;
  }

  const pipeline = loadPipeline();
  const updated = appendToPending(pipeline, lines);
  writeFileSync(PIPELINE_PATH, updated, 'utf-8');

  const { error: updateError } = await supabase
    .from('jobs')
    .update({ synced_to_pipeline: true })
    .in('job_id', syncedIds);

  if (updateError) {
    console.error('Wrote to pipeline.md but failed to mark rows as synced:', updateError.message);
    console.error('Fix manually or you will get duplicate entries next run for:', syncedIds);
    process.exit(1);
  }

  console.log(`Added ${lines.length} job(s) to ${PIPELINE_PATH}. Run '/career-ops pipeline' next.`);
}

main();
