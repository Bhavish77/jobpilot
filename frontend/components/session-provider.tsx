"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { ApiError, api, type User } from "@/lib/api";

interface SessionContextValue {
  user: User | null;
  isLoading: boolean;
  refetch: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

// One /auth/me call per app load, shared via context — every screen that
// needs "who's logged in" reads this instead of each independently
// re-fetching it.
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      const me = await api.get<User>("/auth/me");
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      } else {
        throw err;
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const logout = useCallback(async () => {
    await api.post("/auth/logout");
    setUser(null);
  }, []);

  return (
    <SessionContext.Provider value={{ user, isLoading, refetch, logout }}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
