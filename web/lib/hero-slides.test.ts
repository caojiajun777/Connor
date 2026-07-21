import { describe, expect, it } from "vitest";

import { extractHeroSlides } from "./hero-slides";
import type { PublicReportDetail } from "./types/public";

function makeReport(
  partial: Partial<PublicReportDetail> & { report_date: string },
): PublicReportDetail {
  return {
    title: "t",
    overview: "",
    lead: "",
    keywords: [],
    format: "digest_v1",
    body_sections: [],
    digest: null,
    item_count: 0,
    source_post_count: 0,
    published_at: null,
    previous_report_date: null,
    next_report_date: null,
    items: [],
    ...partial,
  };
}

describe("extractHeroSlides", () => {
  it("pulls digest images in event rank order from latest-first reports", () => {
    const reports = [
      makeReport({
        report_date: "2026-07-20",
        digest: {
          format: "digest_v1",
          toc: [],
          items: [
            {
              rank: 2,
              category: "开发生态",
              headline: "b",
              blurb: "",
              body: "",
              links: [],
              event_id: "2",
              citation_post_ids: [],
              images: [
                {
                  type: "image",
                  url: "/media/b.jpg",
                  width: 800,
                  height: 600,
                  alt_text: "b",
                  position: 0,
                },
              ],
            },
            {
              rank: 1,
              category: "模型发布",
              headline: "a",
              blurb: "",
              body: "",
              links: [],
              event_id: "1",
              citation_post_ids: [],
              images: [
                {
                  type: "image",
                  url: "/media/a.jpg",
                  width: 800,
                  height: 600,
                  alt_text: "a",
                  position: 0,
                },
              ],
            },
          ],
        },
      }),
      makeReport({
        report_date: "2026-07-19",
        digest: {
          format: "digest_v1",
          toc: [],
          items: [
            {
              rank: 1,
              category: "产品",
              headline: "c",
              blurb: "",
              body: "",
              links: [],
              event_id: "3",
              citation_post_ids: [],
              images: [
                {
                  type: "image",
                  url: "/media/c.jpg",
                  width: null,
                  height: null,
                  alt_text: null,
                  position: 0,
                },
              ],
            },
          ],
        },
      }),
    ];

    const slides = extractHeroSlides(reports);
    // Round-robin across reports so older days stay in the reel.
    expect(slides.map((s) => s.url)).toEqual([
      "/media/a.jpg",
      "/media/c.jpg",
      "/media/b.jpg",
    ]);
    expect(slides[0]?.category).toBe("模型发布");
    expect(slides[0]?.signalIndex).toBe(1);
    expect(new Set(slides.map((s) => s.reportDate)).size).toBe(2);
  });

  it("falls back to post media when digest has no images", () => {
    const report = makeReport({
      report_date: "2026-07-18",
      digest: {
        format: "digest_v1",
        toc: [],
        items: [
          {
            rank: 1,
            category: "模型发布",
            headline: "x",
            blurb: "",
            body: "",
            links: [],
            event_id: "1",
            citation_post_ids: [],
            images: [],
          },
        ],
      },
      items: [
        {
          display_order: 1,
          category: "模型发布",
          post: {
            author_name: "A",
            author_handle: "a",
            author_avatar_url: null,
            text_original: "",
            text_translated: "",
            posted_at: "2026-07-18T00:00:00Z",
            original_url: "https://x.com/a/status/1",
            post_type: "original",
            media: [
              {
                type: "image",
                url: "/media/post.jpg",
                width: 100,
                height: 100,
                alt_text: "post",
                position: 0,
              },
              {
                type: "video",
                url: "/media/skip.mp4",
                width: null,
                height: null,
                alt_text: null,
                position: 1,
              },
            ],
            unavailable: false,
            unavailable_reason: null,
          },
        },
      ],
    });

    const slides = extractHeroSlides([report]);
    expect(slides).toHaveLength(1);
    expect(slides[0]?.url).toBe("/media/post.jpg");
  });

  it("dedupes urls and respects maxSlides", () => {
    const report = makeReport({
      report_date: "2026-07-17",
      digest: {
        format: "digest_v1",
        toc: [],
        items: [
          {
            rank: 1,
            category: "A",
            headline: "h",
            blurb: "",
            body: "",
            links: [],
            event_id: "1",
            citation_post_ids: [],
            images: [
              {
                type: "image",
                url: "/media/same.jpg",
                width: null,
                height: null,
                alt_text: null,
                position: 0,
              },
            ],
          },
        ],
      },
      items: [
        {
          display_order: 1,
          category: "A",
          post: {
            author_name: "A",
            author_handle: "a",
            author_avatar_url: null,
            text_original: "",
            text_translated: "",
            posted_at: "2026-07-17T00:00:00Z",
            original_url: "https://x.com/a/status/1",
            post_type: "original",
            media: [
              {
                type: "image",
                url: "/media/same.jpg",
                width: null,
                height: null,
                alt_text: null,
                position: 0,
              },
              {
                type: "image",
                url: "/media/extra.jpg",
                width: null,
                height: null,
                alt_text: null,
                position: 1,
              },
            ],
            unavailable: false,
            unavailable_reason: null,
          },
        },
      ],
    });

    expect(extractHeroSlides([report], { maxSlides: 1 })).toHaveLength(1);
    expect(extractHeroSlides([report]).map((s) => s.url)).toEqual([
      "/media/same.jpg",
      "/media/extra.jpg",
    ]);
  });
});
