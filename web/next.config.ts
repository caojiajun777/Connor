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

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_ORIGIN}/api/:path*`,
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
