export interface TelegramEnv {
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID: string;
}

export function escapeHtml(s: string): string {
  return (s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export async function sendTelegram(
  env: TelegramEnv,
  html: string,
  chatId?: string,
): Promise<void> {
  const chat_id = chatId || env.TELEGRAM_CHAT_ID;
  if (!env.TELEGRAM_BOT_TOKEN || !chat_id) {
    throw new Error("Telegram not configured (BOT_TOKEN / CHAT_ID missing)");
  }
  // Telegram hard limit 4096 chars.
  const text =
    html.length > 3900
      ? html.slice(0, 3900).split("\n").slice(0, -1).join("\n") + "\n\n<i>(truncated)</i>"
      : html;
  const res = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: false,
      }),
    },
  );
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Telegram send failed ${res.status}: ${body.slice(0, 200)}`);
  }
}
