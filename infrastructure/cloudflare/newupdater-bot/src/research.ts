export interface Story {
  title: string;
  text: string;
  url: string;
  published: string;
  source: string;
  sourceType: "news" | "social";
  engagement: number;
  score?: number;
}

const GOOGLE_NEWS = "https://news.google.com/rss/search";
const BLUESKY = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts";
const X_API = "https://api.twitterapis.com/twitter/tweet/advanced_search";

function stripHtml(s: string): string {
  return (s ?? "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function normUrl(u: string): string {
  try {
    const p = new URL(u.trim());
    return `${p.protocol}//${p.hostname.toLowerCase()}${p.pathname.replace(/\/$/, "") || "/"}`.toLowerCase();
  } catch {
    return (u || "").trim().toLowerCase();
  }
}

function normTitle(t: string): string {
  return stripHtml(t)
    .toLowerCase()
    .replace(/\s*[-|:–—]\s*[^-|:–—]{1,60}$/, "")
    .replace(/[^a-z0-9 ]+/g, "")
    .trim();
}

function withinDays(published: string, days: number): boolean {
  if (!published) return true;
  const dt = Date.parse(published);
  if (Number.isNaN(dt)) return true;
  return dt >= Date.now() - (days * 24 + 6) * 3600_000;
}

async function fetchGoogleNews(topic: string, days: number): Promise<Story[]> {
  const url = `${GOOGLE_NEWS}?q=${encodeURIComponent(`${topic} when:${days}d`)}&hl=en-US&gl=US&ceid=US:en`;
  const res = await fetch(url, { headers: { "user-agent": "NewUpdater/0.1" } });
  if (!res.ok) throw new Error(`GoogleNews ${res.status}`);
  const xml = await res.text();
  const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)];
  return items.map((m) => {
    const chunk = m[1];
    const pick = (tag: string) => {
      const mm = chunk.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`));
      let v = mm?.[1] ?? "";
      if (v.startsWith("<![CDATA[")) v = v.slice(9, -3);
      return stripHtml(v);
    };
    return {
      title: pick("title"),
      text: pick("description"),
      url: pick("link"),
      published: pick("pubDate"),
      source: pick("source") || "Google News publisher",
      sourceType: "news" as const,
      engagement: 0,
    };
  });
}

async function fetchBluesky(topic: string, limit = 25): Promise<Story[]> {
  const url = `${BLUESKY}?q=${encodeURIComponent(topic)}&limit=${Math.min(limit, 25)}&sort=latest`;
  const res = await fetch(url, { headers: { "user-agent": "NewUpdater/0.1" } });
  if (!res.ok) throw new Error(`Bluesky ${res.status}`);
  const data = (await res.json()) as any;
  return (data.posts ?? []).map((p: any): Story => {
    const text = stripHtml(p.record?.text ?? "");
    const handle = p.author?.handle ?? "unknown";
    const parts = (p.uri ?? "").split("/");
    const postUrl =
      handle && parts.length >= 3
        ? `https://bsky.app/profile/${handle}/post/${parts[parts.length - 1]}`
        : "";
    return {
      title: text.slice(0, 160) || "Bluesky post",
      text,
      url: postUrl,
      published: p.record?.createdAt ?? "",
      source: `Bluesky @${handle}`,
      sourceType: "social",
      engagement: (p.likeCount ?? 0) + (p.repostCount ?? 0) * 2 + (p.replyCount ?? 0),
    };
  });
}

async function fetchX(topic: string, apiKey: string | undefined, limit = 20): Promise<Story[]> {
  if (!apiKey) return [];
  const url =
    `${X_API}?query=${encodeURIComponent(topic)}&product=Latest&count=${Math.min(limit, 20)}&compact=1`;
  const res = await fetch(url, {
    headers: { authorization: `Bearer ${apiKey}`, "user-agent": "NewUpdater/0.1" },
  });
  if (!res.ok) throw new Error(`X ${res.status}`);
  const data = (await res.json()) as any;
  return (data.tweets ?? []).map((t: any): Story => {
    const text = stripHtml(t.text ?? "");
    const username = t.author?.username ?? "";
    const urlOut = t.url || (username && t.id ? `https://x.com/${username}/status/${t.id}` : "");
    return {
      title: text.slice(0, 160) || "X post",
      text,
      url: urlOut,
      published: t.created_at ?? "",
      source: `X @${username || "unknown"}`,
      sourceType: "social",
      engagement: (t.favorite_count ?? 0) + (t.retweet_count ?? 0) * 2 + (t.reply_count ?? 0),
    };
  });
}

export function rankStories(items: Story[], days = 1): Story[] {
  const seenUrl = new Set<string>();
  const seenTitle = new Set<string>();
  const out: Story[] = [];
  for (const item of items) {
    if (!withinDays(item.published, days)) continue;
    const uk = normUrl(item.url);
    const tk = normTitle(item.title);
    if ((uk && seenUrl.has(uk)) || (tk && seenTitle.has(tk))) continue;
    if (uk) seenUrl.add(uk);
    if (tk) seenTitle.add(tk);

    const text = `${item.title} ${item.text}`.toLowerCase();
    const weights: Array<[string, number]> = [
      ["open source", 3],
      ["ai agent", 3],
      ["artificial intelligence", 2],
      ["launch", 1],
      ["release", 1],
      ["developer", 1],
      ["funding", 1],
      ["security", 1],
    ];
    let relevance = 0;
    for (const [phrase, w] of weights) if (text.includes(phrase)) relevance += w;

    const engPts = Math.min(Math.max(0, item.engagement), 100) / 25;
    const srcPts = item.sourceType === "news" ? 2 : 1;
    const ageH = item.published ? (Date.now() - Date.parse(item.published)) / 3600_000 : NaN;
    const recency = Number.isNaN(ageH) ? 0 : ageH <= 24 ? 1 : ageH <= 72 ? 0.5 : 0;
    item.score = Math.round((relevance + engPts + srcPts + recency) * 100) / 100;
    out.push(item);
  }
  return out.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
}

export async function collectStories(
  topic: string,
  days: number,
  limit: number,
  twitterKey?: string,
): Promise<{ items: Story[]; status: Record<string, string> }> {
  const status: Record<string, string> = {};
  const all: Story[] = [];
  const jobs: Array<[string, Promise<Story[]>]> = [
    ["Google News", fetchGoogleNews(topic, days)],
    ["Bluesky", fetchBluesky(topic)],
  ];
  if (twitterKey) jobs.push(["X", fetchX(topic, twitterKey)]);
  else status["X"] = "Not configured; set TWITTERAPIS_KEY to enable it.";

  for (const [name, job] of jobs) {
    try {
      const r = await job;
      all.push(...r);
      status[name] = `${r.length} result(s)`;
    } catch (e) {
      status[name] = `Unavailable (${e instanceof Error ? e.message : "error"})`;
    }
  }
  return { items: rankStories(all, days).slice(0, limit), status };
}

export async function summarizeWithGroq(
  groqKey: string | undefined,
  topic: string,
  items: Story[],
): Promise<string | null> {
  if (!groqKey || items.length === 0) return null;
  try {
    const bullets = items
      .slice(0, 5)
      .map((s, i) => `${i + 1}. ${s.title} (${s.source}) — ${s.text.slice(0, 200)}`)
      .join("\n");
    const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: { authorization: `Bearer ${groqKey}`, "content-type": "application/json" },
      body: JSON.stringify({
        model: "llama-3.3-70b-versatile",
        temperature: 0.2,
        max_tokens: 400,
        messages: [
          {
            role: "system",
            content:
              "You are NewUpdater. Summarize for developers: what happened, why it matters. 3 bullets max, no invented sources/dates.",
          },
          { role: "user", content: `Topic: ${topic}\nStories:\n${bullets}` },
        ],
      }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as any;
    return data.choices?.[0]?.message?.content?.trim() ?? null;
  } catch {
    return null;
  }
}
