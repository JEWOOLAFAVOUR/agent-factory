import { Hono } from "hono";
import { collectStories, summarizeWithGroq, type Story } from "./research";
import { escapeHtml, sendTelegram } from "./telegram";

interface Env {
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  GROQ_API_KEY?: string;
  TWITTERAPIS_KEY?: string;
  TOPICS?: string;
  SEEN_KV: KVNamespace;
}

const app = new Hono<{ Bindings: Env }>();

function storyKey(s: Story): string {
  const raw = (s.url.trim().toLowerCase() || s.title.trim().toLowerCase()).slice(0, 300);
  let h = 0;
  for (let i = 0; i < raw.length; i++) h = (Math.imul(h, 31) + raw.charCodeAt(i)) | 0;
  return `seen:${(h >>> 0).toString(16)}`;
}

async function filterUnseen(env: Env, items: Story[]): Promise<Story[]> {
  const fresh: Story[] = [];
  for (const s of items) {
    const seen = await env.SEEN_KV.get(storyKey(s));
    if (!seen) fresh.push(s);
  }
  return fresh;
}

async function markSeen(env: Env, items: Story[]): Promise<void> {
  await Promise.all(
    items.map((s) => env.SEEN_KV.put(storyKey(s), "1", { expirationTtl: 7 * 86400 })),
  );
}

function formatDigest(topic: string, items: Story[], aiSummary: string | null, label: string): string {
  const head =
    `<b>NewUpdater — ${escapeHtml(topic)}</b>\n` +
    `<i>${escapeHtml(label)}</i>\n` +
    `<i>Social posts are leads, not verified facts.</i>`;
  const parts = [head];
  if (aiSummary) parts.push(`\n${escapeHtml(aiSummary)}`);
  items.slice(0, 5).forEach((s, i) => {
    const link = s.url ? `<a href="${escapeHtml(s.url)}">Read more</a>` : "No link";
    parts.push(
      `\n<b>${i + 1}. ${escapeHtml(s.title.slice(0, 160))}</b>\n` +
        `<i>${escapeHtml(s.source)} | ${escapeHtml(s.published || "Unknown date")}</i>\n` +
        `${escapeHtml(s.text.slice(0, 220))}\n${link}`,
    );
  });
  return parts.join("\n");
}

async function runDigest(env: Env, label: string): Promise<string> {
  const topics = (env.TOPICS || "AI agents").split(",").map((t) => t.trim()).filter(Boolean);
  let sent = 0;
  for (const topic of topics) {
    const { items } = await collectStories(topic, 1, 8, env.TWITTERAPIS_KEY);
    const fresh = await filterUnseen(env, items);
    if (fresh.length === 0) continue;
    const summary = await summarizeWithGroq(env.GROQ_API_KEY, topic, fresh);
    await sendTelegram(env, formatDigest(topic, fresh, summary, label));
    await markSeen(env, fresh);
    sent += fresh.length;
  }
  return `digest ${label}: ${sent} stories sent across ${topics.length} topics`;
}

app.get("/health", (c) => c.json({ ok: true, service: "newupdater-bot" }));

// Manual trigger: GET /digest/preview?topic=AI%20agents (no send, no KV write)
app.get("/digest/preview", async (c) => {
  const topic = c.req.query("topic") || "AI agents";
  const { items, status } = await collectStories(topic, 1, 5, c.env.TWITTERAPIS_KEY);
  return c.json({ topic, status, items });
});

// Telegram webhook. Set secret via BotFather/webhook so strangers can't push.
app.post("/telegram/webhook", async (c) => {
  const secret = c.env.TELEGRAM_WEBHOOK_SECRET;
  if (secret && c.req.header("x-telegram-bot-api-secret-token") !== secret) {
    return c.text("forbidden", 403);
  }
  const update = (await c.req.json()) as any;
  const msg = update.message;
  const chatId = String(msg?.chat?.id ?? "");
  const text: string = (msg?.text ?? "").trim();
  if (!msg || !chatId) return c.json({ ok: true });

  if (text.startsWith("/start")) {
    await sendTelegram(
      c.env,
      `<b>NewUpdater</b>\n3x daily tech digests.\nCommands:\n/latest &lt;topic&gt; — fresh stories now`,
      chatId,
    );
  } else if (text.startsWith("/latest")) {
    const topic = text.replace("/latest", "").trim() || "AI agents";
    const { items } = await collectStories(topic, 1, 5, c.env.TWITTERAPIS_KEY);
    const fresh = await filterUnseen(c.env, items);
    const summary = await summarizeWithGroq(c.env.GROQ_API_KEY, topic, fresh);
    await sendTelegram(
      c.env,
      formatDigest(topic, fresh.slice(0, 5), summary, "On-demand"),
      chatId,
    );
    await markSeen(c.env, fresh.slice(0, 5));
  } else if (text) {
    await sendTelegram(c.env, `Try /latest AI agents`, chatId);
  }
  return c.json({ ok: true });
});

export default {
  fetch: app.fetch,
  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
    const hour = new Date(event.scheduledTime).getUTCHours();
    const label = hour < 10 ? "Morning digest" : hour < 16 ? "Afternoon digest" : "Night digest";
    ctx.waitUntil(runDigest(env, label));
  },
};
