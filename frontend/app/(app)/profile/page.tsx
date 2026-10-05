"use client";

import { FileUp } from "lucide-react";
// import { Github } from "lucide-react"; // re-enable alongside the GitHub card below
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, api } from "@/lib/api";

// const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"; // re-enable alongside the GitHub card below

interface ActiveResume {
  id: string;
  content: string;
  source_filename: string | null;
  created_at: string;
}

export default function ProfilePage() {
  const { user } = useSession();
  const [resume, setResume] = useState<ActiveResume | null>(null);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .get<ActiveResume>("/resumes/active")
      .then((r) => {
        setResume(r);
        setDraft(r.content);
      })
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
      })
      .finally(() => setIsLoading(false));
  }, []);

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file after an error
    if (!file) return;

    setExtracting(true);
    setMessage(null);
    try {
      const { content } = await api.uploadFile<{ content: string }>("/resumes/extract-pdf", file);
      setDraft(content);
      setMessage("Text extracted — review it below, then save.");
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Couldn't read that PDF.");
    } finally {
      setExtracting(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await api.post("/resumes", { content: draft });
      setMessage("Resume saved.");
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Couldn't save your resume.");
    } finally {
      setSaving(false);
    }
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-bold">Profile</h1>
        <p className="text-muted-foreground">Your account and the resume everything else is tailored from.</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="text-muted-foreground">Name:</span> {user.name ?? "—"}
          </p>
          <p>
            <span className="text-muted-foreground">Email:</span> {user.email}
          </p>
          <p className="text-muted-foreground">
            {user.google_linked ? "Google account linked." : "Signed up with email/password."}
          </p>
        </CardContent>
      </Card>

      {/* Commented out for now, per request — the GitHub connect flow
          itself still works server-side (/auth/github/connect), this
          just hides the entry point on the Profile page. Re-enable by
          uncommenting this block + the Github icon import + API_URL above. */}
      {/* <Card>
        <CardHeader>
          <CardTitle>GitHub</CardTitle>
          <CardDescription>
            Optional — grants read access to your repos for future RAG grounding. Never required to use
            JobPilot.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {user.github_linked ? (
            <p className="flex items-center gap-2 text-sm">
              <Github className="size-4" />
              Connected as <span className="font-medium">{user.github_username}</span>
            </p>
          ) : (
            <Button variant="outline" asChild>
              <a href={`${API_URL}/auth/github/connect`}>
                <Github className="size-4" />
                Connect GitHub
              </a>
            </Button>
          )}
        </CardContent>
      </Card> */}

      <Card>
        <CardHeader>
          <CardTitle>Resume</CardTitle>
          <CardDescription>
            This is what every tailored resume, cover letter, and interview prep curriculum is grounded
            in. Upload a PDF to extract its text, or paste/edit it directly — either way, review it below
            before saving.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Spinner className="size-5" />
          ) : (
            <form onSubmit={handleSave} className="space-y-3">
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf"
                onChange={handleFileSelect}
                className="hidden"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={extracting}
              >
                {extracting ? (
                  <>
                    <Spinner className="size-4" />
                    Extracting text…
                  </>
                ) : (
                  <>
                    <FileUp className="size-4" />
                    Upload PDF
                  </>
                )}
              </Button>

              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={14}
                placeholder="Paste your resume text here, or upload a PDF above…"
                className="w-full rounded-md border border-input bg-card p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              {message && <p className="text-sm text-muted-foreground">{message}</p>}
              <Button type="submit" variant="accent" disabled={saving}>
                {saving ? "Saving…" : resume ? "Save changes" : "Save resume"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
