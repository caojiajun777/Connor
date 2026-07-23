import type { Metadata } from "next";
import { Suspense } from "react";

import { AnalyticsBeacon } from "@/components/shared/AnalyticsBeacon";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Connor",
    template: "%s — Connor",
  },
  description:
    "Connor publishes a daily public briefing on frontier AI signals — curated, translated, and easy to read.",
  metadataBase: new URL(
    process.env.CONNOR_PUBLIC_SITE_URL ?? "http://localhost:3000",
  ),
  icons: {
    icon: [
      { url: "/icon.png", type: "image/png", sizes: "512x512" },
      { url: "/favicon.ico", sizes: "48x48" },
    ],
    apple: [{ url: "/apple-icon.png", sizes: "180x180" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="font-sans antialiased">
        <Suspense fallback={null}>
          <AnalyticsBeacon />
        </Suspense>
        {children}
      </body>
    </html>
  );
}
