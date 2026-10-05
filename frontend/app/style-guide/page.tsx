import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

// Phase 6, chunk 1's real deliverable (docs/PHASE_6_PLAN.md) — not a
// screen end users ever see, a page to sanity-check the palette/type
// scale/primitives once, before 10 real screens get built on top of
// them. Toggle the OS/browser color scheme to check dark mode too
// (next-themes defaults to "system").
export default function StyleGuidePage() {
  const swatches = [
    { label: "background", className: "bg-background border border-border" },
    { label: "card", className: "bg-card border border-border" },
    { label: "muted", className: "bg-muted" },
    { label: "primary", className: "bg-primary" },
    { label: "accent", className: "bg-accent" },
    { label: "destructive", className: "bg-destructive" },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-12 px-6 py-12">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold">Design system</h1>
        <p className="text-muted-foreground">Phase 6, chunk 1 — tokens, type scale, and primitives.</p>
      </header>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Color tokens</h2>
        <div className="grid grid-cols-3 gap-4 sm:grid-cols-6">
          {swatches.map((s) => (
            <div key={s.label} className="space-y-1.5">
              <div className={`h-16 w-full rounded-md ${s.className}`} />
              <p className="text-xs text-muted-foreground">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Type scale</h2>
        <div className="space-y-2">
          <p className="text-4xl font-bold">text-4xl font-bold</p>
          <p className="text-2xl font-semibold">text-2xl font-semibold</p>
          <p className="text-lg font-semibold">text-lg font-semibold</p>
          <p className="text-base">text-base — body copy</p>
          <p className="text-sm text-muted-foreground">text-sm text-muted-foreground — secondary text</p>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Buttons</h2>
        <div className="flex flex-wrap gap-3">
          <Button variant="accent">Accent (Prepare / Apply)</Button>
          <Button variant="primary">Primary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="link">Link</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm">Small</Button>
          <Button size="md">Medium</Button>
          <Button size="lg">Large</Button>
          <Button disabled>Disabled</Button>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Pipeline status badges</h2>
        <div className="flex flex-wrap gap-3">
          <Badge variant="preparing">Preparing</Badge>
          <Badge variant="ready_to_apply">Ready to apply</Badge>
          <Badge variant="applied">Applied</Badge>
          <Badge variant="interviewing">Interviewing</Badge>
          <Badge variant="muted">Muted</Badge>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Form + feedback</h2>
        <div className="flex max-w-sm flex-col gap-3">
          <Input placeholder="you@example.com" />
          <Input placeholder="Disabled" disabled />
          <div className="flex items-center gap-2">
            <Spinner />
            <span className="text-sm text-muted-foreground">Loading…</span>
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Avatar + card</h2>
        <div className="flex items-center gap-4">
          <Avatar>
            <AvatarFallback>JP</AvatarFallback>
          </Avatar>
          <Card className="flex-1">
            <CardHeader>
              <CardTitle>Senior Backend Engineer</CardTitle>
              <CardDescription>Anthropic — Remote</CardDescription>
            </CardHeader>
            <CardContent>
              <Badge variant="ready_to_apply">Ready to apply</Badge>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}
