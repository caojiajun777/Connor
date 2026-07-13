import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { extractPosts } from "../services/x.js";
import { findChromeExecutable } from "../services/browser.js";

test("extractPosts returns structured post data", async () => {
  const browser = await chromium.launch({ executablePath: findChromeExecutable(), headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`
      <article data-testid="tweet">
        <div data-testid="socialContext">Pinned</div>
        <div data-testid="User-Name"><a href="/ModelLab"><span>Model Lab</span><span>@ModelLab</span></a></div>
        <a href="/ModelLab/status/987654"><time datetime="2026-07-11T10:00:00.000Z"></time></a>
        <div data-testid="tweetText">A new model is coming soon.</div>
        <div data-testid="tweetPhoto">
          <img src="https://pbs.twimg.com/media/abc123.jpg" alt="model selector screenshot" />
        </div>
        <div data-testid="card.wrapper"><span>Official docs</span><span>example.com</span></div>
        <button data-testid="reply" aria-label="12 replies"></button>
        <button data-testid="retweet" aria-label="34 reposts"></button>
        <button data-testid="like" aria-label="56 likes"></button>
        <a href="/ModelLab/status/987654/analytics" aria-label="789 views"></a>
      </article>
    `);
    const posts = await extractPosts(page);
    assert.equal(posts.length, 1);
    assert.deepEqual(posts[0], {
      post_id: "987654",
      url: "https://x.com/ModelLab/status/987654",
      author_name: "Model Lab",
      author_handle: "@ModelLab",
      created_at: "2026-07-11T10:00:00.000Z",
      text: "A new model is coming soon.",
      social_context: "Pinned",
      reply_label: "12 replies",
      repost_label: "34 reposts",
      like_label: "56 likes",
      view_label: "789 views",
      has_media: true,
      media: [
        {
          url: "https://pbs.twimg.com/media/abc123.jpg",
          media_type: "image",
          alt_text: "model selector screenshot"
        }
      ],
      quoted_text: null,
      quoted_url: null,
      quoted_handle: null,
      link_card_title: "Official docs"
    });
  } finally {
    await browser.close();
  }
});
