import type { MetadataRoute } from "next";

import { listReports } from "@/lib/api/reports";

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base =
    process.env.CONNOR_PUBLIC_SITE_URL?.replace(/\/$/, "") ??
    "http://localhost:3000";

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${base}/`, changeFrequency: "daily", priority: 1 },
    { url: `${base}/archive`, changeFrequency: "daily", priority: 0.8 },
    { url: `${base}/about`, changeFrequency: "monthly", priority: 0.5 },
  ];

  try {
    const { items } = await listReports({ limit: 365 });
    const reportRoutes = items.map((item) => ({
      url: `${base}/daily/${item.report_date}`,
      lastModified: item.published_at
        ? new Date(item.published_at)
        : new Date(item.report_date),
      changeFrequency: "weekly" as const,
      priority: item.is_latest ? 0.85 : 0.7,
    }));
    return [...staticRoutes, ...reportRoutes];
  } catch {
    return staticRoutes;
  }
}
