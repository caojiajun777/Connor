import type { NextConfig } from "next";

const API_ORIGIN = process.env.CONNOR_PUBLIC_API_BASE ?? "http://127.0.0.1:8080";

function remotePatternsFromEnv(): NonNullable<
  NextConfig["images"]
>["remotePatterns"] {
  const patterns: NonNullable<NextConfig["images"]>["remotePatterns"] = [
    { protocol: "http", hostname: "127.0.0.1", port: "8080", pathname: "/**" },
    { protocol: "http", hostname: "localhost", port: "8080", pathname: "/**" },
    { protocol: "https", hostname: "pbs.twimg.com", pathname: "/**" },
    { protocol: "https", hostname: "abs.twimg.com", pathname: "/**" },
    { protocol: "https", hostname: "video.twimg.com", pathname: "/**" },
  ];

  const candidates = [
    process.env.CONNOR_MEDIA_PUBLIC_BASE_URL,
    process.env.CONNOR_PUBLIC_SITE_URL,
    process.env.CONNOR_PUBLIC_API_BASE,
  ];

  for (const raw of candidates) {
    const value = (raw || "").trim();
    if (!value || value.startsWith("/")) continue;
    try {
      const u = new URL(value);
      if (u.protocol !== "http:" && u.protocol !== "https:") continue;
      patterns.push({
        protocol: u.protocol.replace(":", "") as "http" | "https",
        hostname: u.hostname,
        ...(u.port ? { port: u.port } : {}),
        pathname: "/**",
      });
    } catch {
      // ignore invalid URLs
    }
  }

  return patterns;
}

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=()",
  },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "base-uri 'self'",
      "frame-ancestors 'none'",
      "object-src 'none'",
      "img-src 'self' data: blob: https://pbs.twimg.com https://abs.twimg.com",
      "media-src 'self' https://video.twimg.com https://pbs.twimg.com",
      "font-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      "script-src 'self' 'unsafe-inline'",
      "connect-src 'self'",
      "form-action 'self'",
    ].join("; "),
  },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
  async rewrites() {
    // Public surface only — never proxy console/ops to the internet hostname.
    return [
      {
        source: "/api/public/meta",
        destination: `${API_ORIGIN}/api/public/meta`,
      },
      {
        source: "/api/public/reports",
        destination: `${API_ORIGIN}/api/public/reports`,
      },
      {
        source: "/api/public/reports/:path*",
        destination: `${API_ORIGIN}/api/public/reports/:path*`,
      },
      {
        source: "/api/public/analytics/:path*",
        destination: `${API_ORIGIN}/api/public/analytics/:path*`,
      },
      {
        source: "/media/:path*",
        destination: `${API_ORIGIN}/media/:path*`,
      },
    ];
  },
  images: {
    remotePatterns: remotePatternsFromEnv(),
  },
};

export default nextConfig;
