"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
          background: "#fbfbfd",
          color: "#1d1d1f",
        }}
      >
        <div style={{ textAlign: "center", padding: "2rem" }}>
          <p
            style={{
              margin: 0,
              fontSize: 12,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "#0066cc",
            }}
          >
            Connor
          </p>
          <h1 style={{ margin: "12px 0 0", fontSize: 32 }}>
            Something went wrong
          </h1>
          <p style={{ margin: "12px 0 0", color: "#6e6e73" }}>
            Please retry, or return home.
          </p>
          <div
            style={{
              marginTop: 28,
              display: "flex",
              gap: 16,
              justifyContent: "center",
            }}
          >
            <button
              type="button"
              onClick={reset}
              style={{
                height: 44,
                padding: "0 20px",
                border: 0,
                borderRadius: 999,
                background: "#0066cc",
                color: "#fff",
                fontSize: 15,
                cursor: "pointer",
              }}
            >
              Retry
            </button>
            <Link href="/" style={{ color: "#0066cc", alignSelf: "center" }}>
              Home
            </Link>
          </div>
        </div>
      </body>
    </html>
  );
}
