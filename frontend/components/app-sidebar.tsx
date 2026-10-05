"use client";

import { Compass, KanbanSquare, LogOut, User as UserIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useSession } from "@/components/session-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/discover", label: "Discover", icon: Compass },
  { href: "/pipeline", label: "Pipeline", icon: KanbanSquare },
  { href: "/profile", label: "Profile", icon: UserIcon },
];

function initials(name: string | null, email: string) {
  if (name) {
    const parts = name.trim().split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return email[0].toUpperCase();
}

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useSession();

  async function handleLogout() {
    await logout();
    router.push("/");
  }

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-card">
      <div className="flex items-center justify-between px-6 py-5">
        <Link href="/discover" className="text-lg font-bold">
          JobPilot
        </Link>
        <ThemeToggle />
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {NAV_ITEMS.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active ? "bg-primary text-primary-foreground" : "text-foreground hover:bg-muted"
              )}
            >
              <item.icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {user && (
        <div className="flex items-center gap-3 border-t border-border px-4 py-4">
          <Avatar>
            <AvatarImage src={user.avatar_url ?? undefined} alt={user.name ?? user.email} />
            <AvatarFallback>{initials(user.name, user.email)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{user.name ?? user.email}</p>
            <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          </div>
          <Button variant="ghost" size="icon" aria-label="Log out" onClick={handleLogout}>
            <LogOut className="size-4" />
          </Button>
        </div>
      )}
    </aside>
  );
}
