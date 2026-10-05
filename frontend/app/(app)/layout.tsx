"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useSession } from "@/components/session-provider";
import { Spinner } from "@/components/ui/spinner";

// Every screen under this route group (Discover/Pipeline/Profile/Job
// Workspace) shares this one auth gate + sidebar — a screen only needs
// to exist inside app/(app)/ to get both for free.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, isLoading } = useSession();

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
  }, [isLoading, user, router]);

  if (isLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="size-6" />
      </div>
    );
  }

  return (
    // h-screen + overflow-hidden on the shell, not min-h-screen — the
    // page itself must never scroll, only main's own overflow-y-auto
    // should. With min-h-screen, the sidebar (not position: sticky/fixed)
    // scrolled away with the page the moment content overflowed.
    <div className="flex h-screen overflow-hidden">
      <AppSidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
