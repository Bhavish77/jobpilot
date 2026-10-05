"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, api, type Application } from "@/lib/api";

// "interviewing" deliberately excluded — nothing in the backend can ever
// move an application into that status (no Applied -> Interviewing
// transition exists; see applications.py's own docstring), so showing an
// always-empty column here would just be confusing, not useful.
const COLUMNS: { status: Application["status"]; label: string }[] = [
  { status: "preparing", label: "Preparing" },
  { status: "ready_to_apply", label: "Ready to apply" },
  { status: "applied", label: "Applied" },
];

export default function PipelinePage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    return api
      .get<{ applications: Application[] }>("/applications")
      .then((data) => setApplications(data.applications))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load your pipeline."))
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    load();
    // Live update (Phase 5's Notify WebSocket, via components/notify-listener.tsx)
    // — a "tailoring_ready" push means some application's status just
    // changed server-side, so the board re-fetches instead of looking
    // stale until the user manually reloads.
    window.addEventListener("jobpilot:tailoring_ready", load);
    return () => window.removeEventListener("jobpilot:tailoring_ready", load);
  }, []);

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Spinner className="size-6" />
      </div>
    );
  }

  return (
    <div className="space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-bold">Pipeline</h1>
        <p className="text-muted-foreground">Everything you&apos;ve started preparing, tracked to Applied.</p>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {COLUMNS.map((column) => {
          const cards = applications.filter((a) => a.status === column.status);
          return (
            <div key={column.status} className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-muted-foreground">{column.label}</h2>
                <Badge variant={column.status}>{cards.length}</Badge>
              </div>
              <div className="space-y-2">
                {cards.map((application) => (
                  <Link key={application.id} href={`/pipeline/${application.jobPostingId}`}>
                    <Card className="transition-shadow hover:shadow-md">
                      <CardHeader>
                        <CardTitle className="text-sm">{application.title}</CardTitle>
                        {application.company && <CardDescription>{application.company}</CardDescription>}
                      </CardHeader>
                    </Card>
                  </Link>
                ))}
                {cards.length === 0 && (
                  <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
                    Nothing here yet
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
