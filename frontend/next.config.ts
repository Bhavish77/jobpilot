import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Dev-native, not containerized (see docs/PHASE_6_PLAN.md) — runs
  // against agent-core/notify's published Docker ports over localhost,
  // same as any other local client of this API.
};

export default nextConfig;
