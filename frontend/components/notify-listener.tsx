"use client";

import { useEffect, useRef } from "react";

import { useSession } from "@/components/session-provider";
import { useToast } from "@/components/toast-provider";

const NOTIFY_URL = process.env.NEXT_PUBLIC_NOTIFY_URL ?? "ws://localhost:4000";

// One connection for the whole app, opened once a real session exists —
// the browser sends the same jobpilot_session cookie on the WebSocket
// upgrade automatically (confirmed for real in Phase 5), no token to
// attach manually. Reconnects on close while the user is still logged in
// (a dropped connection shouldn't mean silently missing every push for
// the rest of the session).
export function NotifyListener() {
  const { user } = useSession();
  const { addToast } = useToast();
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!user) return;

    let cancelled = false;

    function connect() {
      const ws = new WebSocket(NOTIFY_URL);
      socketRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "tailoring_ready") {
            addToast("Your application is ready to apply — tailored resume and cover letter are in.");
            window.dispatchEvent(new CustomEvent("jobpilot:tailoring_ready", { detail: data }));
          }
        } catch {
          // Non-JSON or unrecognized event — ignore rather than crash the listener.
        }
      };

      ws.onclose = () => {
        if (!cancelled) setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      cancelled = true;
      socketRef.current?.close();
    };
  }, [user, addToast]);

  return null;
}
