"""
evaluate_job.py

Give it a job posting URL or a local PDF, and it tells you whether the role
is worth applying to — scored against your resume and your minimum salary
threshold from config.py.

Usage:
    python evaluate_job.py --url "https://example.com/jobs/123"
    python evaluate_job.py --pdf "/path/to/job_description.pdf"
    python evaluate_job.py --text "paste the JD text directly"

Does NOT require Supabase to be configured — this is meant to also work as a
quick, local, on-demand check. Results are appended to evaluated_jobs.jsonl
so you keep a history even without a database.
"""

import argparse
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import pdfplumber
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

import config
from llm_client import primary_client
from score_jobs import format_resume_to_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

RESULTS_LOG = "evaluated_jobs.jsonl"


# --- Structured LLM output ---

class JobEvaluation(BaseModel):
    job_title: str = Field(description="Job title extracted from the posting")
    company: str = Field(description="Company name extracted from the posting")
    location: str = Field(description="Location, or 'Remote' if it's a remote role")
    is_remote: bool = Field(description="True if this role can be done remotely")
    salary_mentioned: str = Field(description="Salary/comp range as stated in the posting, or 'Not specified'")
    salary_estimate_annual_usd: Optional[int] = Field(
        default=None,
        description="Your best-effort estimate of the annual salary in USD if a range is given or can be inferred from level/location/market; null if truly unknowable",
    )
    fit_score: int = Field(description="0-100 suitability score of this candidate for this role, based only on the resume and job description provided")
    matching_strengths: list[str] = Field(description="3-5 concrete reasons this candidate fits, referencing specific resume items")
    gaps_or_concerns: list[str] = Field(description="Concrete gaps, mismatches, or red flags (vague JD, unrealistic requirements, likely underpaid, etc.)")
    verdict: str = Field(description="One of: 'Strong match - apply', 'Worth applying', 'Borderline', 'Skip'")
    reasoning: str = Field(description="2-4 sentence explanation for the verdict, in plain language")


# --- Extraction helpers ---

def extract_text_from_url(url: str) -> Optional[str]:
    """Fetch a job posting page and pull out the main readable text."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Could not fetch URL {url}: {e}")
        return None

    content_type = resp.headers.get("Content-Type", "")
    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return _extract_text_from_pdf_bytes(resp.content)

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = "\n".join(lines)

    if len(cleaned) < 200:
        logger.warning(
            "Extracted very little text from this URL — the page may be JS-rendered "
            "(common on LinkedIn/Indeed/Glassdoor). Try saving the JD as a PDF and "
            "using --pdf instead, or paste it with --text."
        )
    return cleaned or None


def _extract_text_from_pdf_bytes(data: bytes) -> Optional[str]:
    text = ""
    try:
        with io.BytesIO(data) as f, pdfplumber.open(f) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        logger.error(f"Failed to parse PDF: {e}")
        return None
    return text.strip() or None


def extract_text_from_local_pdf(path: str) -> Optional[str]:
    if not os.path.exists(path):
        logger.error(f"PDF not found at: {path}")
        return None
    with open(path, "rb") as f:
        return _extract_text_from_pdf_bytes(f.read())


def load_resume_text() -> Optional[str]:
    resume_path = getattr(config, "BASE_RESUME_PATH", "resume.json")
    if not os.path.exists(resume_path):
        logger.error(
            f"No resume found at '{resume_path}'. Run the resume parser first "
            f"(see README) or place a resume.json in the project root."
        )
        return None
    with open(resume_path, "r", encoding="utf-8") as f:
        resume_data = json.load(f)
    return format_resume_to_text(resume_data)


# --- Core evaluation ---

def evaluate(jd_text: str, resume_text: str) -> Optional[JobEvaluation]:
    min_salary = getattr(config, "MIN_SALARY_USD", None)
    remote_only = getattr(config, "REMOTE_ONLY", False)

    prompt = f"""
You are a careful, honest job-fit evaluator helping a candidate decide whether
a role is worth their time to apply to. Be direct and skeptical — do not
inflate scores to be nice.

--- CANDIDATE RESUME ---
{resume_text}
--- END RESUME ---

--- JOB POSTING (raw extracted text) ---
{jd_text[:15000]}
--- END JOB POSTING ---

Candidate's minimum acceptable annual salary: {f"${min_salary:,} USD" if min_salary else "not specified"}
Candidate requires remote: {remote_only}

Evaluate this posting for this specific candidate. If salary isn't stated,
give your best-effort market estimate based on title/level/location/company,
and say so in your reasoning rather than treating it as a hard fact.
If the posting looks low-effort, scammy, a duplicate listing, or wildly
unrealistic (e.g. asks for 10 years experience in a 2-year-old technology),
call that out as a concern.
"""
    try:
        raw = primary_client.generate_content(
            prompt=prompt,
            system_prompt="You output only valid JSON matching the requested schema.",
            temperature=0.2,
            response_format=JobEvaluation,
        )
        return JobEvaluation.model_validate_json(raw)
    except Exception as e:
        logger.error(f"LLM evaluation failed: {e}")
        return None


def print_report(ev: JobEvaluation):
    min_salary = getattr(config, "MIN_SALARY_USD", None)
    print("\n" + "=" * 60)
    print(f"{ev.job_title}  @  {ev.company}")
    print(f"{ev.location}{'  (Remote)' if ev.is_remote else ''}")
    print("-" * 60)
    print(f"Fit score:        {ev.fit_score}/100")
    print(f"Salary mentioned: {ev.salary_mentioned}")
    if ev.salary_estimate_annual_usd:
        flag = ""
        if min_salary and ev.salary_estimate_annual_usd < min_salary:
            flag = f"  ⚠ below your ${min_salary:,} threshold"
        print(f"Salary estimate:  ~${ev.salary_estimate_annual_usd:,}/yr{flag}")
    print(f"\nVERDICT: {ev.verdict}")
    print(f"{ev.reasoning}")
    print("\nStrengths:")
    for s in ev.matching_strengths:
        print(f"  + {s}")
    if ev.gaps_or_concerns:
        print("\nGaps / concerns:")
        for g in ev.gaps_or_concerns:
            print(f"  - {g}")
    print("=" * 60 + "\n")


def save_result(source: str, ev: JobEvaluation):
    record = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "source": source, **ev.model_dump()}
    with open(RESULTS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    logger.info(f"Saved to {RESULTS_LOG}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate a job posting against your resume.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="URL of the job posting")
    group.add_argument("--pdf", help="Path to a local PDF of the job description")
    group.add_argument("--text", help="Raw job description text, pasted directly")
    args = parser.parse_args()

    if not config.LLM_API_KEY:
        logger.error("LLM_API_KEY (or GEMINI_API_KEY) is not set.")
        sys.exit(1)

    resume_text = load_resume_text()
    if not resume_text:
        sys.exit(1)

    if args.url:
        jd_text = extract_text_from_url(args.url)
        source = args.url
    elif args.pdf:
        jd_text = extract_text_from_local_pdf(args.pdf)
        source = args.pdf
    else:
        jd_text = args.text
        source = "pasted-text"

    if not jd_text:
        logger.error("Could not extract any job description text. Try --text and paste it manually.")
        sys.exit(1)

    ev = evaluate(jd_text, resume_text)
    if not ev:
        sys.exit(1)

    print_report(ev)
    save_result(source, ev)


if __name__ == "__main__":
    main()
