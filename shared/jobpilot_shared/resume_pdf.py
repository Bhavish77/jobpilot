"""Resume text -> PDF compiler + verification — Phase 4, chunk 6b/6c/6d.

The Resume Agent's output (graph/agents/resume.py) is markdown-ish, not
literal Markdown by spec, but close enough that a real Markdown parser
handles it correctly: section headers are a whole paragraph that's
entirely one **bold** run (`**PROFESSIONAL SUMMARY**` on its own line),
bullets use the standard `*   text` syntax with inline **bold** labels
inside a longer line (`*   **Languages:** Python, Go`). Using `markdown`
instead of a hand-rolled parser gets paragraph/list handling right for
free; the one thing it can't do on its own is tell "whole line is bold"
(an intended section header) apart from "bold label inside a longer
bullet line" (just emphasis) — both become identical <strong> tags.
Fixed with one CSS selector (`p > strong:only-child`) instead of a custom
parser: it matches exactly the paragraphs that are nothing but a single
bold run, which is exactly the section-header shape and never the
bullet-label shape.

No persistent storage for the output bytes (see docs/PHASE_4_PLAN.md,
chunk 6's scope note) — this is a pure function of already-persisted
`Application.resume_output` text, re-run on demand rather than cached.

Chunk 6c/6d: verification is split into two independently-testable
checks, same reasoning as every other gate in this codebase (quality
gate, circuit breaker) — a single compiled PDF, two different questions
asked of it: did it fit the page (`check_page_overflow`), and would an
ATS actually be able to read it (`verify_ats_text`)?
"""

import re

import markdown
import pymupdf
import weasyprint

from jobpilot_shared.text_matching import extract_keywords

PAGE_CSS = """
@page { size: Letter; margin: 0.6in; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.35; color: #1a1a1a; }
p { margin: 0 0 6px 0; }
p > strong:only-child {
    display: block;
    font-size: 12.5pt;
    border-bottom: 1px solid #333;
    padding-bottom: 2px;
    margin-top: 10px;
}
ul { margin: 2px 0 8px 0; padding-left: 18px; }
li { margin-bottom: 3px; }
"""

def compile_resume_pdf(resume_text: str) -> bytes:
    html_body = markdown.markdown(resume_text)
    html = f"<html><head><style>{PAGE_CSS}</style></head><body>{html_body}</body></html>"
    return weasyprint.HTML(string=html).write_pdf()


def check_page_overflow(pdf_bytes: bytes, max_pages: int = 1) -> dict:
    """Page count is a direct, deterministic overflow signal here because
    PAGE_CSS fixes a real @page size — WeasyPrint already decided whether
    the content fits, this just reads that decision back out."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count
    return {"page_count": page_count, "overflow": page_count > max_pages}


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\-.\s()]{8,}\d)")


def verify_ats_text(pdf_bytes: bytes, job_description: str) -> dict:
    """What an ATS parser actually does: pull the text layer in reading
    order and look for *an* email/phone shape in it as real text, not a
    rendered image of a resume. Deliberately pattern-based rather than
    checking against one known-correct value (e.g. `User.email`) — the
    email a candidate lists on their actual resume is frequently not the
    one they registered JobPilot with, so asserting equality to the
    account email would fail perfectly good resumes. A resume that looks
    fine on screen but has its text flattened into an image (or contact
    info only in an image/logo) passes a human eyeball check and fails
    every real ATS — this is the check that catches that category of
    failure before chunk 6f ever marks an application ready to apply."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)

    email_found = bool(_EMAIL_RE.search(full_text))
    phone_found = bool(_PHONE_RE.search(full_text))

    jd_keywords = extract_keywords(job_description)
    resume_keywords = extract_keywords(full_text)
    overlap = jd_keywords & resume_keywords
    keyword_coverage = len(overlap) / len(jd_keywords) if jd_keywords else 1.0

    return {
        "email_found": email_found,
        "phone_found": phone_found,
        "keyword_coverage": keyword_coverage,
        "matched_keywords": sorted(overlap),
        "text_extracted": bool(full_text.strip()),
    }


_BULLET_RE = re.compile(r"^\s*\*\s+")


def _score_bullet(bullet_line: str, jd_keywords: set[str], cover_letter_keywords: set[str]) -> float:
    bullet_keywords = extract_keywords(bullet_line)
    # JD relevance counts full weight; being referenced by the cover
    # letter counts half — losing a line the cover letter builds on
    # would make the two documents inconsistent, so it's worth something,
    # just not as much as actually matching what the job asked for.
    return len(bullet_keywords & jd_keywords) + 0.5 * len(bullet_keywords & cover_letter_keywords)


def cut_lowest_relevance_line(resume_text: str, job_description: str, cover_letter_text: str = "") -> str | None:
    """Only bullet lines (`*   ...`) are ever cut — headers, the summary,
    and contact info stay untouched no matter how page-constrained this
    gets. Returns None once there's nothing left that's safe to cut."""
    lines = resume_text.split("\n")
    bullets = [(i, line) for i, line in enumerate(lines) if _BULLET_RE.match(line)]
    if not bullets:
        return None

    jd_keywords = extract_keywords(job_description)
    cl_keywords = extract_keywords(cover_letter_text)
    cut_idx, _ = min(bullets, key=lambda pair: _score_bullet(pair[1], jd_keywords, cl_keywords))

    return "\n".join(line for i, line in enumerate(lines) if i != cut_idx)


def fit_resume_to_page(
    resume_text: str, job_description: str, cover_letter_text: str = "", max_attempts: int = 15
) -> dict:
    """The actual chunk 6 loop: compile, check overflow, cut the single
    lowest-relevance bullet if it overflows, repeat. Bounded by
    max_attempts rather than "until it fits" — a resume with no bullets
    at all (or one page's worth of non-bullet content alone that's
    already over the limit) can't be fixed by cutting bullets, and this
    must still return rather than loop forever in that case."""
    current = resume_text
    pdf = compile_resume_pdf(current)

    for attempt in range(max_attempts):
        overflow = check_page_overflow(pdf)
        if not overflow["overflow"]:
            return {"resume_text": current, "pdf_bytes": pdf, "attempts": attempt, "fit": True}

        trimmed = cut_lowest_relevance_line(current, job_description, cover_letter_text)
        if trimmed is None:
            return {"resume_text": current, "pdf_bytes": pdf, "attempts": attempt, "fit": False}

        current = trimmed
        pdf = compile_resume_pdf(current)

    return {
        "resume_text": current,
        "pdf_bytes": pdf,
        "attempts": max_attempts,
        "fit": not check_page_overflow(pdf)["overflow"],
    }
