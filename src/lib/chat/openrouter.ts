/**
 * OpenRouter chat completion with sequential model fallback.
 * Tries MODEL_1..MODEL_5 from .env in order, then a couple of well-known
 * free OpenRouter models as a last resort, per spec: "if all 5 fail, fall
 * back to another free OpenRouter model automatically."
 */

const CONFIGURED_MODELS = [
  process.env.MODEL_1,
  process.env.MODEL_2,
  process.env.MODEL_3,
  process.env.MODEL_4,
  process.env.MODEL_5,
].filter((m): m is string => !!m);

const EXTRA_FALLBACK_MODELS = [
  "google/gemma-2-9b-it:free",
  "meta-llama/llama-3.2-3b-instruct:free",
  "mistralai/mistral-7b-instruct:free",
];

const TIMEOUT_MS = 45_000;

export interface ChatCompletionMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ChatCompletionResult {
  content: string;
  model: string;
}

async function tryModel(model: string, messages: ChatCompletionMessage[], apiKey: string): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ model, messages }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText}${body ? ` — ${body.slice(0, 200)}` : ""}`);
    }
    const data = await res.json();
    const content = data?.choices?.[0]?.message?.content;
    if (typeof content !== "string" || !content.trim()) throw new Error("Empty response");
    return content;
  } finally {
    clearTimeout(timer);
  }
}

/** Tries each model in order (configured 5, then generic free fallbacks); throws only if all fail. */
export async function chatCompletion(messages: ChatCompletionMessage[]): Promise<ChatCompletionResult> {
  const apiKey = process.env.OPENROUTER_KEY;
  if (!apiKey) throw new Error("OPENROUTER_KEY tidak ditemukan di .env");

  const candidates = [...CONFIGURED_MODELS, ...EXTRA_FALLBACK_MODELS];
  const errors: string[] = [];
  for (const model of candidates) {
    try {
      const content = await tryModel(model, messages, apiKey);
      return { content, model };
    } catch (err) {
      errors.push(`${model}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  throw new Error(`Semua model gagal:\n${errors.join("\n")}`);
}
