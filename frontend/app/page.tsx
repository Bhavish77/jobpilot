import { CheckCircle2, FileText, MessageSquareText, Sparkles, Target } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ThemeToggle } from "@/components/theme-toggle";

const FEATURES = [
  {
    icon: Target,
    title: "Smart job matching",
    description:
      "Every posting is scored against your real resume, so you spend time on the jobs worth applying to — not every listing on the board.",
  },
  {
    icon: FileText,
    title: "Tailored resume & cover letter",
    description:
      "A specialist agent drafts both grounded in your actual background for each job, then a second critique-and-revise pass catches missed keywords before you ever see it.",
  },
  {
    icon: MessageSquareText,
    title: "Interview prep that's actually useful",
    description:
      "A curriculum built from the real gaps between your background and the job description — then a chat you can practice answers with.",
  },
  {
    icon: CheckCircle2,
    title: "You're always in control",
    description:
      "JobPilot prepares. It never submits anything on your behalf — you review every resume, cover letter, and the job itself before you apply.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <span className="text-lg font-bold">JobPilot</span>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button variant="ghost" asChild>
            <Link href="/login">Log in</Link>
          </Button>
          <Button variant="accent" asChild>
            <Link href="/register">Get started</Link>
          </Button>
        </div>
      </header>

      <main className="flex-1">
        <section className="mx-auto max-w-3xl px-6 py-24 text-center">
          <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-sm text-muted-foreground">
            <Sparkles className="size-4" />
            AI-prepared, human-submitted
          </div>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
            A tailored resume and cover letter for every job — in minutes, not hours.
          </h1>
          <p className="mt-6 text-lg text-muted-foreground">
            JobPilot finds relevant postings, drafts a resume and cover letter grounded in your real
            background, and builds interview prep from the specific gaps that job exposes. You review
            everything and apply yourself — JobPilot never submits an application for you.
          </p>
          <div className="mt-10 flex items-center justify-center gap-4">
            <Button size="lg" variant="accent" asChild>
              <Link href="/register">Get started free</Link>
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link href="/login">Log in</Link>
            </Button>
          </div>
        </section>

        <section className="border-t border-border bg-muted/40 px-6 py-20">
          <div className="mx-auto max-w-5xl">
            <h2 className="text-center text-2xl font-semibold">How it works</h2>
            <div className="mt-10 grid gap-6 sm:grid-cols-2">
              {FEATURES.map((feature) => (
                <Card key={feature.title}>
                  <CardHeader>
                    <feature.icon className="size-6 text-accent" />
                    <CardTitle className="mt-2">{feature.title}</CardTitle>
                    <CardDescription>{feature.description}</CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          </div>
        </section>

        <section className="px-6 py-20 text-center">
          <h2 className="text-2xl font-semibold">Ready to stop writing the same resume twenty times?</h2>
          <div className="mt-8">
            <Button size="lg" variant="accent" asChild>
              <Link href="/register">Get started free</Link>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t border-border px-6 py-8 text-center text-sm text-muted-foreground">
        © {new Date().getFullYear()} JobPilot. Prepares your applications — you decide when to send them.
      </footer>
    </div>
  );
}
