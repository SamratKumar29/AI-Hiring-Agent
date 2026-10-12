import pytest

from brain import ingest_links as il


def test_normalize_dedup_keys():
    a = il.normalize_url("HTTPS://WWW.Example.com/Jobs/123/?utm_source=x&gclid=1#frag")
    assert a == "https://www.example.com/Jobs/123"
    assert il.normalize_url("https://x.com/a?b=1&utm_campaign=z") == "https://x.com/a?b=1"


def test_extract_from_text_markdown_and_cleanup():
    t = """Check [Anthropic](https://job-boards.greenhouse.io/anthropic/jobs/4020159008).
    Also <https://jobs.lever.co/acme/123e4567-e89b-12d3-a456-426614174000>, and "https://www.linkedin.com/jobs/search/?keywords=ai".
    dup: https://job-boards.greenhouse.io/anthropic/jobs/4020159008?utm_source=newsletter
    bare www.naukri.com/ai-engineer-jobs-in-bengaluru and trailing dot https://remoteok.com/remote-ai-jobs."""
    urls = il.extract_urls(t)
    assert len(urls) == 5
    assert urls[0] == "https://job-boards.greenhouse.io/anthropic/jobs/4020159008"
    assert "https://www.naukri.com/ai-engineer-jobs-in-bengaluru" in urls
    assert urls[-1] == "https://remoteok.com/remote-ai-jobs"


def test_extract_from_files(tmp_path):
    (tmp_path / "l.md").write_text("- https://a.example.com/careers\n- https://b.example.com/jobs/123456\n")
    assert len(il.extract_urls(tmp_path / "l.md")) == 2
    assert len(il.extract_urls(str(tmp_path / "l.md"))) == 2
    (tmp_path / "x.exe").write_bytes(b"x")
    with pytest.raises(ValueError):
        il.extract_urls(str(tmp_path / "x.exe"))
    with pytest.raises(FileNotFoundError):
        il.extract_urls("missing.pdf")


def make_pdf(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawString(50, 800, "Visible text link: https://jobs.ashbyhq.com/openai/abc-123")
    c.drawString(50, 760, "Apply here")                                   # label only: URL is an annotation
    c.linkURL("https://boards.greenhouse.io/gitlab/jobs/6789012", (50, 755, 120, 775))
    c.drawString(50, 700, "Wrapped: https://www.michaelpage.co.in/job-detail/senior-ai-")
    c.drawString(50, 685, "engineer/ref/jn-102025-6804321")
    c.showPage()
    c.drawString(50, 800, "page 2: https://in.indeed.com/viewjob?jk=abcdef0123456789&utm_source=x")
    c.save()


def test_pdf_text_annotations_and_wrapped_urls(tmp_path):
    f = tmp_path / "links.pdf"
    make_pdf(f)
    urls = il.extract_urls(f)
    assert "https://boards.greenhouse.io/gitlab/jobs/6789012" in urls                       # annotation only
    assert "https://jobs.ashbyhq.com/openai/abc-123" in urls                                # plain text
    assert "https://www.michaelpage.co.in/job-detail/senior-ai-engineer/ref/jn-102025-6804321" in urls  # wrapped
    assert any("in.indeed.com/viewjob" in u for u in urls)                                  # page 2
    assert len(urls) == 4


def test_docx_hyperlinks_and_text(tmp_path):
    import docx
    d = docx.Document()
    d.add_paragraph("Text: https://jobs.lever.co/acme/123e4567-e89b-12d3-a456-426614174000")
    rid = d.part.relate_to("https://apply.workable.com/foo/j/ABC123/", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    assert rid
    f = tmp_path / "l.docx"
    d.save(f)
    urls = il.extract_urls(f)
    assert len(urls) == 2 and any("workable" in u for u in urls)


CASES = [
    # url, type, board, ats, company
    ("https://www.linkedin.com/jobs/view/senior-ai-engineer-at-acme-3912345678/?trk=public_jobs", "single_posting", "linkedin", None, None),
    ("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=3912345678", "single_posting", "linkedin", None, None),
    ("https://www.linkedin.com/jobs/search/?keywords=ai%20engineer&location=India", "board_search", "linkedin", None, None),
    ("https://in.indeed.com/viewjob?jk=abcdef0123456789", "single_posting", "indeed", None, None),
    ("https://in.indeed.com/jobs?q=ai+engineer&l=Bengaluru", "board_search", "indeed", None, None),
    ("https://www.naukri.com/job-listings-ai-engineer-acme-bengaluru-3-to-6-years-101025001234", "single_posting", "naukri", None, None),
    ("https://www.naukri.com/ai-engineer-jobs-in-bengaluru", "board_search", "naukri", None, None),
    ("https://wellfound.com/jobs/3456789-senior-ml-engineer", "single_posting", "wellfound", None, None),
    ("https://wellfound.com/role/l/machine-learning-engineer/india", "board_search", "wellfound", None, None),
    ("https://remoteok.com/remote-jobs/remote-senior-ai-engineer-acme-1098765", "single_posting", "remoteok", None, None),
    ("https://remoteok.com/remote-ai-jobs", "board_search", "remoteok", None, None),
    ("https://www.michaelpage.co.in/job-detail/ai-engineer/ref/jn-102025-6804321", "single_posting", "michaelpage", None, None),
    ("https://www.michaelpage.co.in/jobs/technology", "board_search", "michaelpage", None, None),
    ("https://job-boards.greenhouse.io/anthropic/jobs/4020159008", "single_posting", None, "greenhouse", "Anthropic"),
    ("https://boards.greenhouse.io/gitlab", "company_careers", None, "greenhouse", "Gitlab"),
    ("https://jobs.lever.co/acme-corp/123e4567-e89b-12d3-a456-426614174000", "single_posting", None, "lever", "Acme Corp"),
    ("https://jobs.lever.co/acme-corp", "company_careers", None, "lever", "Acme Corp"),
    ("https://jobs.ashbyhq.com/openai", "company_careers", None, "ashby", "Openai"),
    ("https://apply.workable.com/foo/j/ABC123/", "single_posting", None, "workable", "Foo"),
    ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/India-Bengaluru/AI-Engineer_JR1990001", "single_posting", None, "workday", "Nvidia"),
    ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "company_careers", None, "workday", "Nvidia"),
    ("https://acme.com/careers?gh_jid=4020159008", "single_posting", None, "greenhouse", None),
    ("https://careers.acme.com/jobs/senior-ai-engineer-12345", "single_posting", None, None, None),
    ("https://acme.com/careers", "company_careers", None, None, "Acme"),
    ("https://acme.com/en/jobs/search", "unknown", None, None, None),
    ("https://twitter.com/someone/status/123", "unknown", None, None, None),
    ("https://acme.com/blog/how-we-hire", "unknown", None, None, None),
]


@pytest.mark.parametrize("url,typ,board,ats,company", CASES)
def test_classify(url, typ, board, ats, company):
    r = il.classify(url)
    assert (r["type"], r["board"], r["ats"], r["company"]) == (typ, board, ats, company), r


def test_linkedin_and_indeed_canonicalised_so_variants_dedupe():
    a = il.classify("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=3912345678")["url"]
    b = il.classify("https://in.linkedin.com/jobs/view/ai-engineer-3912345678?trk=x")["url"]
    assert a == b == "https://www.linkedin.com/jobs/view/3912345678"
    assert il.classify("https://in.indeed.com/rc/clk?jk=abc123&fccid=1")["url"] == "https://in.indeed.com/viewjob?jk=abc123"


def test_extract_and_classify_preview():
    r = il.extract_and_classify("https://jobs.lever.co/acme https://acme.com/blog/post")
    assert [x["type"] for x in r] == ["company_careers", "unknown"] and r[0]["original"] == "https://jobs.lever.co/acme"
