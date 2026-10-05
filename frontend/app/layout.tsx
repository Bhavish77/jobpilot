import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { NotifyListener } from "@/components/notify-listener";
import { SessionProvider } from "@/components/session-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { ToastProvider } from "@/components/toast-provider";

import "./globals.css";

// One font family throughout, loaded once here — no per-page font
// swapping, no extra network request beyond this (next/font self-hosts
// it at build time, no layout shift on load).
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "JobPilot",
  description: "AI-prepared resumes, cover letters, and interview prep — you apply, we prepare.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <SessionProvider>
            <ToastProvider>
              <NotifyListener />
              {children}
            </ToastProvider>
          </SessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
