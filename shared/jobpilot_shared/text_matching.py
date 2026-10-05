"""Shared keyword tokenizer — Phase 4's ATS keyword-overlap check
(resume_pdf.py) and Phase 6's job match-score query (jobs.py) both need
the exact same "what counts as a meaningful keyword" logic; written once
here instead of two independently-drifting copies.
"""

import re

# Common filler words excluded from keyword-overlap scoring — otherwise
# "and"/"the"/"with" would dominate the overlap count and make everything
# look equally "relevant."
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "with", "for", "to", "of", "in",
    "on", "at", "is", "are", "be", "as", "this", "that", "will", "you",
    "your", "we", "our", "us",
}

# Allows '.'/'#'/'-' mid-token so things like "node.js"/"c#" survive intact.
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.#-]{1,}")


def extract_keywords(text: str) -> set[str]:
    # That same permissive character class also swallows a trailing
    # sentence period ("experience." before the next sentence) — stripped
    # off explicitly so "experience." and "experience" aren't treated as
    # two different keywords.
    words = (w.strip(".,;:!?") for w in _WORD_RE.findall(text.lower()))
    return {w for w in words if w not in STOPWORDS and len(w) > 2}
