import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        muted: "bg-muted text-muted-foreground",
        // One variant per Pipeline column (see globals.css) — status is
        // conveyed by color *and* text together, never color alone.
        preparing: "bg-status-preparing-bg text-status-preparing-fg",
        ready_to_apply: "bg-status-ready-bg text-status-ready-fg",
        applied: "bg-status-applied-bg text-status-applied-fg",
        interviewing: "bg-status-interviewing-bg text-status-interviewing-fg",
      },
    },
    defaultVariants: {
      variant: "muted",
    },
  }
);

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}

export { Badge, badgeVariants };
