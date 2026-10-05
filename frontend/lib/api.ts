// Typed fetch wrapper for agent-core. `credentials: "include"` on every
// call is the one non-negotiable line here — the session is an httpOnly
// cookie (agent-core/app/routers/auth.py), never a token this code can
// read or attach itself; without it every authenticated request would
// silently 401.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body — fall back to statusText above.
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

async function uploadFile<T>(path: string, file: File): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  // No Content-Type header here on purpose — the browser sets its own
  // multipart boundary when the body is a FormData, and overriding it
  // manually breaks the boundary the server expects.
  const res = await fetch(`${API_URL}${path}`, { method: "POST", credentials: "include", body: formData });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // Non-JSON error body — fall back to statusText above.
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  uploadFile,
};

// --- Response shapes, matching agent-core's actual router responses ---

export interface User {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  google_linked: boolean;
  github_linked: boolean;
  github_username: string | null;
}

export interface JobPosting {
  id: string;
  title: string;
  company: string;
  location: string | null;
  is_remote: boolean;
  url: string;
  description: string;
  tags: string[];
  salary_min: number | null;
  salary_max: number | null;
  match_score: number;
}

export interface PdfCheck {
  email_found: boolean;
  phone_found: boolean;
  keyword_coverage: number;
  matched_keywords: string[];
  text_extracted: boolean;
  page_fit: boolean;
  cut_attempts: number;
}

export interface PrepareStep {
  key: "quality_check" | "resume" | "cover_letter" | "curriculum" | "review" | "finalize";
  label: string;
  done: boolean;
}

export interface PrepareStatus {
  status:
    | "not_started"
    | "in_progress"
    | "failed"
    | "pending_review"
    | "insufficient_resume"
    | "resume_finalized"
    | "reviewed_accepted"
    | "reviewed_kept_original"
    | "review_parse_failed";
  error?: string | null;
  rejection_reason?: string | null;
  resume_output?: string | null;
  cover_letter_output?: string | null;
  curriculum?: string | null;
  pdf_check?: PdfCheck | null;
  steps?: PrepareStep[];
  review?: {
    original_resume: string;
    proposed_resume: string;
    original_cover_letter: string;
    proposed_cover_letter: string;
  };
}

export interface InterviewMessage {
  role: "user" | "assistant";
  content: string;
}

export interface Application {
  id: string;
  status: "preparing" | "ready_to_apply" | "applied" | "interviewing";
  version: number;
  jobPostingId: string;
  title: string;
  company: string | null;
}
