"use client";

import { Check, FileCheck2, FileText, GraduationCap, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import type { PrepareStep } from "@/lib/api";
import { cn } from "@/lib/utils";

const STEP_ICONS: Record<PrepareStep["key"], typeof FileText> = {
  quality_check: ShieldCheck,
  resume: FileText,
  cover_letter: Mail,
  curriculum: GraduationCap,
  review: Sparkles,
  finalize: FileCheck2,
};

// Purely ambient flavor text under the active step — not tied to real
// backend state, rotates on its own. The point is making a 60-180 second
// real wait (this project's own earlier measurement) feel alive instead
// of dead air; the step list above it is the real, honest signal.
const FLAVOR_TEXT = [
  "Matching your experience to what this role actually asks for…",
  "Finding the words that make your background land…",
  "Cross-checking claims against your real background…",
  "Making sure nothing's invented that isn't in your resume…",
  "Almost there…",
];

export function PrepareProgress({ steps }: { steps: PrepareStep[] }) {
  const [flavorIndex, setFlavorIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setFlavorIndex((i) => (i + 1) % FLAVOR_TEXT.length), 3500);
    return () => clearInterval(interval);
  }, []);

  const doneCount = steps.filter((s) => s.done).length;
  const activeIndex = steps.findIndex((s) => !s.done);

  return (
    <div className="rounded-lg border border-border bg-card p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="font-semibold">Preparing your application</h2>
          <p className="text-sm text-muted-foreground transition-opacity duration-500">
            {FLAVOR_TEXT[flavorIndex]}
          </p>
        </div>
        <span className="text-sm font-medium text-muted-foreground">
          {doneCount}/{steps.length}
        </span>
      </div>

      <div>
        {steps.map((step, i) => {
          const Icon = STEP_ICONS[step.key];
          const isActive = i === activeIndex;
          const isPending = !step.done && !isActive;
          const isLast = i === steps.length - 1;

          return (
            <div key={step.key} className="flex gap-4">
              {/* Icon column: badge + connecting line, standard stepper
                  layout — the line is a flex sibling that stretches to
                  fill the row instead of being absolutely positioned, so
                  it never drifts out of alignment with the icon size. */}
              <div className="flex flex-col items-center">
                <div className="relative flex items-center justify-center">
                  {isActive && (
                    <span className="absolute inline-flex h-9 w-9 animate-ping rounded-full bg-accent/40" />
                  )}
                  <div
                    className={cn(
                      "relative flex size-9 shrink-0 items-center justify-center rounded-full border-2 transition-colors duration-500",
                      step.done && "border-accent bg-accent text-accent-foreground",
                      isActive && "border-accent text-accent",
                      isPending && "border-border text-muted-foreground"
                    )}
                  >
                    {step.done ? (
                      <Check className="size-4" />
                    ) : (
                      <Icon className={cn("size-4", isActive && "animate-pulse")} />
                    )}
                  </div>
                </div>
                {!isLast && (
                  <div
                    className={cn(
                      "my-1 w-px flex-1 transition-colors duration-500",
                      step.done ? "bg-accent" : "bg-border"
                    )}
                    aria-hidden
                  />
                )}
              </div>
              <span
                className={cn(
                  "pb-6 pt-1.5 text-sm transition-colors duration-500",
                  step.done && "text-foreground",
                  isActive && "font-medium text-foreground",
                  isPending && "text-muted-foreground"
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
