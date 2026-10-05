import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// Standard shadcn/ui pattern: clsx for conditional classes, tailwind-merge
// so a later conflicting class (e.g. a caller's own "p-4") wins over a
// component's default instead of both ending up in the output.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
