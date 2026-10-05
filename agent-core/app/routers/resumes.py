"""POST /resumes, GET /resumes/active, POST /resumes/extract-pdf — Phase 3
+ Phase 6 polish.

Closes a gap that's existed since Phase 2 started: every test of
/prepare or /interview needed a manual `INSERT INTO resumes` via psql,
because nothing let a real user create a Resume row. No RAG here — see
docs/PHASE_3_PLAN.md for why chunking/embeddings/retrieval are deferred;
this is plain CRUD.

/extract-pdf is deliberately *extraction only*, no DB write — PyMuPDF is
already a backend dependency (resume_pdf.py's ATS text-layer check), so
reusing it here for resume intake needs no new library. Returns the
extracted text for the frontend to show in an editable textarea rather
than saving it blind: PDF text extraction is good, not perfect (column
layouts, tables, and unusual fonts can come out garbled), and the
existing POST /resumes is still the one real save path either way.
"""

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.db import get_session
from jobpilot_shared.models import Resume, User

from app.deps import get_current_user

router = APIRouter(prefix="/resumes", tags=["resumes"])


class ResumeUploadRequest(BaseModel):
    content: str
    source_filename: str | None = None


@router.post("")
async def upload_resume(
    req: ResumeUploadRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Resume content can't be empty.")

    # Only one active resume per user — every existing query (Resume Agent,
    # Interview Prep, the /prepare quality gate) filters is_active=True and
    # assumes exactly one row matches. Deactivate the old one atomically
    # with inserting the new one, in the same transaction.
    await session.execute(
        update(Resume).where(Resume.user_id == user.id, Resume.is_active.is_(True)).values(is_active=False)
    )

    resume = Resume(
        user_id=user.id,
        content=req.content,
        source_filename=req.source_filename,
        is_active=True,
    )
    session.add(resume)
    await session.commit()
    await session.refresh(resume)

    return {"id": str(resume.id), "created_at": resume.created_at.isoformat()}


@router.post("/extract-pdf")
async def extract_pdf(
    file: UploadFile,
    user: User = Depends(get_current_user),  # noqa: ARG001 - auth gate only, extraction needs no user data
) -> dict:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    pdf_bytes = await file.read()
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
    except Exception as exc:  # noqa: BLE001 - a malformed/corrupt upload, not a server bug
        raise HTTPException(status_code=400, detail=f"Couldn't read that PDF: {exc}") from exc

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No extractable text found — this PDF might be a scanned image rather than real text.",
        )

    return {"content": text}


@router.get("/active")
async def get_active_resume(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(Resume)
        .where(Resume.user_id == user.id, Resume.is_active.is_(True))
        .order_by(Resume.created_at.desc())
    )
    resume = result.scalars().first()
    if resume is None:
        raise HTTPException(status_code=404, detail="No active resume yet.")

    return {
        "id": str(resume.id),
        "content": resume.content,
        "source_filename": resume.source_filename,
        "created_at": resume.created_at.isoformat(),
    }
