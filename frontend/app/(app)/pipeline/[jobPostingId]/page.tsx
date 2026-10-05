"use client";

import { ArrowLeft, Send } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PrepareProgress } from "@/components/prepare-progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ApiError,
  api,
  type Application,
  type InterviewMessage,
  type PrepareStatus,
} from "@/lib/api";

const ACTIVE_STATUSES = new Set(["not_started", "in_progress"]);

const STATUS_LABELS: Record<Application["status"], string> = {
  preparing: "Preparing",
  ready_to_apply: "Ready to apply",
  applied: "Applied",
  interviewing: "Interviewing",
};

export default function JobWorkspacePage() {
  const params = useParams<{ jobPostingId: string }>();
  const jobPostingId = decodeURIComponent(params.jobPostingId);

  const [application, setApplication] = useState<Application | null>(null);
  const [prepareStatus, setPrepareStatus] = useState<PrepareStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [applying, setApplying] = useState(false);
  const [retrying, setRetrying] = useState(false);

  async function load() {
    const [{ applications }, status] = await Promise.all([
      api.get<{ applications: Application[] }>("/applications"),
      api.get<PrepareStatus>(`/prepare/${encodeURIComponent(jobPostingId)}/status`),
    ]);
    setApplication(applications.find((a) => a.jobPostingId === jobPostingId) ?? null);
    setPrepareStatus(status);
  }

  useEffect(() => {
    load()
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load this job."))
      .finally(() => setIsLoading(false));
  }, [jobPostingId]);

  // Poll while the pipeline is actually running — stops itself the
  // moment the real status leaves "not_started"/"in_progress", so this
  // never polls a finished application.
  useEffect(() => {
    if (!prepareStatus || !ACTIVE_STATUSES.has(prepareStatus.status)) return;
    const interval = setInterval(() => {
      api.get<PrepareStatus>(`/prepare/${encodeURIComponent(jobPostingId)}/status`).then(setPrepareStatus);
    }, 3000);
    return () => clearInterval(interval);
  }, [prepareStatus, jobPostingId]);

  async function handleDecision(decision: "accept" | "reject") {
    setDeciding(true);
    try {
      await api.post(`/prepare/${encodeURIComponent(jobPostingId)}/approve`, { decision });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't record your decision.");
    } finally {
      setDeciding(false);
    }
  }

  async function handleRetry() {
    setRetrying(true);
    setError(null);
    try {
      // No job_description needed — the backend resolves it from the
      // real JobPosting row by id (chunk: optional job_description).
      await api.post("/prepare", { job_posting_id: jobPostingId });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't retry.");
    } finally {
      setRetrying(false);
    }
  }

  async function handleApply() {
    if (!application) return;
    setApplying(true);
    try {
      await api.post(`/applications/${encodeURIComponent(jobPostingId)}/apply`, {
        version: application.version,
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't mark this as applied.");
    } finally {
      setApplying(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Spinner className="size-6" />
      </div>
    );
  }

  if (!application) {
    return <p className="px-6 py-10 text-destructive">{error ?? "Application not found."}</p>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-6 py-10">
      <Link
        href="/pipeline"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Back to Pipeline
      </Link>

      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">{application.title}</h1>
          {application.company && <p className="text-muted-foreground">{application.company}</p>}
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={application.status}>{STATUS_LABELS[application.status]}</Badge>
          {application.status === "ready_to_apply" && (
            <Button variant="accent" onClick={handleApply} disabled={applying}>
              {applying ? "Marking…" : "Mark as applied"}
            </Button>
          )}
        </div>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {prepareStatus && ACTIVE_STATUSES.has(prepareStatus.status) && prepareStatus.steps && (
        <PrepareProgress steps={prepareStatus.steps} />
      )}

      {prepareStatus?.status === "failed" && (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="space-y-3 py-6">
            <p className="text-sm text-destructive">{prepareStatus.error ?? "Preparation failed."}</p>
            {prepareStatus.steps && (
              <p className="text-xs text-muted-foreground">
                Progress is saved — retrying picks up from where it stopped, not from scratch.
              </p>
            )}
            <Button variant="outline" size="sm" onClick={handleRetry} disabled={retrying}>
              {retrying ? "Retrying…" : "Retry"}
            </Button>
          </CardContent>
        </Card>
      )}

      {prepareStatus?.status === "pending_review" && prepareStatus.review && (
        <ReviewCard review={prepareStatus.review} onDecide={handleDecision} deciding={deciding} />
      )}

      {prepareStatus?.status === "insufficient_resume" && (
        <Card>
          <CardContent className="py-4 text-sm text-destructive">{prepareStatus.rejection_reason}</CardContent>
        </Card>
      )}

      {prepareStatus?.resume_output && (
        <Tabs defaultValue="resume">
          <TabsList>
            <TabsTrigger value="resume">Resume</TabsTrigger>
            <TabsTrigger value="cover_letter">Cover letter</TabsTrigger>
            <TabsTrigger value="interview">Interview prep</TabsTrigger>
          </TabsList>

          <TabsContent value="resume">
            <Card>
              <CardContent className="whitespace-pre-wrap py-6 text-sm">
                {prepareStatus.resume_output}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="cover_letter">
            <Card>
              <CardContent className="whitespace-pre-wrap py-6 text-sm">
                {prepareStatus.cover_letter_output}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="interview">
            <InterviewChat jobPostingId={jobPostingId} curriculum={prepareStatus.curriculum} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

function ReviewCard({
  review,
  onDecide,
  deciding,
}: {
  review: NonNullable<PrepareStatus["review"]>;
  onDecide: (decision: "accept" | "reject") => void;
  deciding: boolean;
}) {
  return (
    <Card className="border-status-ready-fg/30 bg-status-ready-bg/30">
      <CardContent className="space-y-4 py-6">
        <p className="font-medium">A reviewer pass proposed improvements — accept or keep the original.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Original resume</p>
            <p className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-card p-3 text-xs">
              {review.original_resume}
            </p>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Proposed resume</p>
            <p className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-card p-3 text-xs">
              {review.proposed_resume}
            </p>
          </div>
        </div>
        <div className="flex gap-3">
          <Button variant="accent" onClick={() => onDecide("accept")} disabled={deciding}>
            Accept proposed version
          </Button>
          <Button variant="outline" onClick={() => onDecide("reject")} disabled={deciding}>
            Keep original
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function InterviewChat({ jobPostingId, curriculum }: { jobPostingId: string; curriculum?: string | null }) {
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .get<{ messages: InterviewMessage[] }>(`/interview/${encodeURIComponent(jobPostingId)}/history`)
      .then((data) => setMessages(data.messages));
  }, [jobPostingId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    if (!input.trim()) return;
    const userMessage: InterviewMessage = { role: "user", content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setSending(true);
    try {
      const { reply } = await api.post<{ reply: string }>("/interview/turn", {
        job_posting_id: jobPostingId,
        job_description: curriculum ?? "",
        message: userMessage.content,
      });
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <Card>
      <CardContent className="flex h-[28rem] flex-col gap-4 py-6">
        {curriculum && (
          <details className="rounded-md border border-border bg-muted/50 p-3 text-xs">
            <summary className="cursor-pointer font-medium">Study curriculum</summary>
            <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{curriculum}</p>
          </details>
        )}
        <div className="flex-1 space-y-3 overflow-y-auto">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                m.role === "user" ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"
              }`}
            >
              {m.content}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex gap-2"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Answer or ask a question…"
            disabled={sending}
          />
          <Button type="submit" size="icon" disabled={sending}>
            <Send className="size-4" />
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
