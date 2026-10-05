"use client";

import { ChevronDown, MapPin, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, api, type JobPosting } from "@/lib/api";
import { cn } from "@/lib/utils";

// Reuses the Pipeline status badge colors for a different purpose here —
// not a status, just a quick visual "is this worth a look" signal so the
// list is scannable by color, not just by reading every percentage.
function matchBadgeVariant(score: number): "applied" | "ready_to_apply" | "muted" {
  if (score >= 0.15) return "applied";
  if (score >= 0.08) return "ready_to_apply";
  return "muted";
}

export default function DiscoverPage() {
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [hasResume, setHasResume] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [preparing, setPreparing] = useState(false);
  const [preparedIds, setPreparedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    api
      .get<{ jobs: JobPosting[]; total: number; has_resume: boolean }>("/jobs?limit=30")
      .then((data) => {
        setJobs(data.jobs);
        setHasResume(data.has_resume);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load jobs."))
      .finally(() => setIsLoading(false));
  }, []);

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function prepareOne(job: JobPosting) {
    await api.post("/prepare", { job_posting_id: job.id, job_description: job.description });
    setPreparedIds((prev) => new Set(prev).add(job.id));
  }

  async function handlePrepareSelected() {
    setPreparing(true);
    try {
      const toPrepare = jobs.filter((j) => selected.has(j.id));
      await Promise.all(toPrepare.map((job) => prepareOne(job)));
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start preparing one or more jobs.");
    } finally {
      setPreparing(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-6 py-10">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Discover</h1>
          <p className="text-muted-foreground">Ranked by keyword match against your active resume.</p>
        </div>
        {selected.size > 0 && (
          <Button variant="accent" onClick={handlePrepareSelected} disabled={preparing}>
            {preparing ? "Preparing…" : `Prepare ${selected.size} application${selected.size > 1 ? "s" : ""}`}
          </Button>
        )}
      </header>

      {!hasResume && (
        <Card className="border-status-preparing-fg/30 bg-status-preparing-bg/40">
          <CardContent className="flex items-center justify-between py-4">
            <p className="text-sm">Upload a resume to get real match scores for these jobs.</p>
            <Button variant="outline" size="sm" asChild>
              <Link href="/profile">Upload resume</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}

      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spinner className="size-6" />
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => {
            const isExpanded = expanded.has(job.id);
            const isPrepared = preparedIds.has(job.id);
            return (
              <Card key={job.id} className="transition-shadow hover:shadow-md">
                <CardHeader className="flex-row items-start gap-4 space-y-0">
                  <Checkbox
                    checked={selected.has(job.id)}
                    onCheckedChange={() => toggleSelected(job.id)}
                    className="mt-1"
                    aria-label={`Select ${job.title}`}
                  />
                  <div className="flex-1">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="font-semibold">{job.title}</h3>
                        <p className="text-sm text-muted-foreground">{job.company}</p>
                      </div>
                      <Badge variant={matchBadgeVariant(job.match_score)} className="shrink-0 gap-1">
                        <Sparkles className="size-3" />
                        {Math.round(job.match_score * 100)}% keyword match
                      </Badge>
                    </div>
                    <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                      {job.location && (
                        <span className="flex items-center gap-1">
                          <MapPin className="size-3" />
                          {job.location}
                        </span>
                      )}
                      {job.is_remote && <Badge variant="muted">Remote</Badge>}
                    </div>

                    <button
                      onClick={() => toggleExpanded(job.id)}
                      className="mt-3 flex items-center gap-1 text-sm text-primary hover:underline"
                    >
                      {isExpanded ? "Hide description" : "Show description"}
                      <ChevronDown className={cn("size-4 transition-transform", isExpanded && "rotate-180")} />
                    </button>
                    {isExpanded && (
                      <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">
                        {job.description}
                      </p>
                    )}

                    <div className="mt-4 flex items-center gap-3">
                      <Button
                        size="sm"
                        variant="accent"
                        disabled={isPrepared}
                        onClick={() => prepareOne(job)}
                      >
                        {isPrepared ? "Preparing started" : "Prepare"}
                      </Button>
                      <a
                        href={job.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sm text-muted-foreground hover:underline"
                      >
                        View original posting
                      </a>
                    </div>
                  </div>
                </CardHeader>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
