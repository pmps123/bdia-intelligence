/**
 * Product intelligence: token analysis and dynamic candidate generation.
 * No product name, variant, prefix, suffix, alias or abbreviation is predefined —
 * everything is derived from the uploaded corpus itself.
 */

import { levenshteinRatio } from "@/lib/engine/similarity";

export function tokenize(normalized: string): string[] {
  return normalized
    .split(/\s+/)
    .flatMap((t) =>
      // split digit<->letter boundaries so "40KG" and "40 KG" produce identical
      // tokens regardless of how a vendor happened to write them
      t
        .replace(/(\d)(\p{L})/gu, "$1 $2")
        .replace(/(\p{L})(\d)/gu, "$1 $2")
        .split(" ")
    )
    .map((t) => t.replace(/^[.,]+|[.,]+$/g, ""))
    .filter((t) => t.length > 0);
}

export type TokenClass = "numeric" | "code" | "measure" | "word";

export function classifyToken(t: string): TokenClass {
  if (/^\d+([.,]\d+)?$/.test(t)) return "numeric";
  if (/^\d+([.,]\d+)?[\p{L}%]+$/u.test(t)) return "measure"; // e.g. quantity+unit patterns like 20MM, 5KG
  if (/\d/.test(t) && /[\p{L}]/u.test(t)) return "code";
  if (/^\d{4,}$/.test(t)) return "code";
  return "word";
}

/** Compute IDF-like informativeness of each token across a corpus of token lists. */
export function buildIdf(corpus: string[][]): Map<string, number> {
  const df = new Map<string, number>();
  for (const tokens of corpus) {
    for (const t of new Set(tokens)) df.set(t, (df.get(t) ?? 0) + 1);
  }
  const n = Math.max(corpus.length, 1);
  const idf = new Map<string, number>();
  for (const [t, d] of df) idf.set(t, Math.log(1 + n / d));
  // normalize to mean 1 so weights stay comparable across corpora
  let sum = 0;
  for (const v of idf.values()) sum += v;
  const mean = sum / Math.max(idf.size, 1) || 1;
  for (const [t, v] of idf) idf.set(t, v / mean);
  return idf;
}

/**
 * Detect a shared "product code" token dynamically: a code-classed token that
 * appears in both strings is a strong signal, discovered — not configured.
 */
export function sharedCodeTokens(a: string[], b: string[]): string[] {
  const codesA = new Set(a.filter((t) => classifyToken(t) === "code" || classifyToken(t) === "measure"));
  return b.filter((t) => codesA.has(t));
}

/** Canonical form of a product code: case/spacing/punctuation never distinguish two codes. */
export function cleanCode(s: string): string {
  return s.normalize("NFKC").toUpperCase().replace(/[^\p{L}\p{N}]/gu, "");
}

/**
 * Code-identity signal between a vendor and internal row.
 *
 * Vendor and internal files rarely share the same column layout — one side
 * may have a dedicated "Code" column while the other only embeds the code
 * inside the product name (or neither, or both). This never assumes
 * symmetry: a dedicated code on one side is compared against the other
 * side's code-classed name tokens instead of requiring both sides to have
 * the same column mapped.
 */
export function codeSimilarity(
  vCode: string | null,
  vTokens: string[],
  iCode: string | null,
  iTokens: string[]
): { score: number; weight: number } {
  const vCodeTokens = vTokens.filter((t) => classifyToken(t) !== "word");
  const iCodeTokens = iTokens.filter((t) => classifyToken(t) !== "word");

  if (vCode && iCode) {
    const c1 = cleanCode(vCode);
    const c2 = cleanCode(iCode);
    const score = c1 === c2 && c1 !== "" ? 1 : levenshteinRatio(c1, c2) >= 0.85 ? 0.7 : 0;
    return { score, weight: score === 1 ? 4 : score > 0 ? 2 : 0 };
  }

  if (vCode || iCode) {
    // Dedicated code on one side only — look for it in the other side's
    // name. tokenize() always splits at digit<->letter boundaries, so a
    // fused code like "EU309" never survives as a single token ("EU309
    // 2500W" tokenizes to "EU","309","2500","W") — comparing the dedicated
    // code against one token at a time would never find it. Instead, glue
    // the other side's tokens back together and look for the code as a
    // contiguous substring, with a per-token fuzzy fallback for typos.
    const dedicated = cleanCode((vCode || iCode) as string);
    const otherTokens = (vCode ? iTokens : vTokens).map(cleanCode).filter(Boolean);
    let best = 0;
    if (dedicated && otherTokens.join("").includes(dedicated)) {
      best = 1;
    } else {
      for (const t of otherTokens) best = Math.max(best, levenshteinRatio(t, dedicated));
    }
    if (best >= 0.85) return { score: best, weight: best >= 0.999 ? 3.5 : 1.8 };
    // fall through to the plain token-overlap fallback below
  }

  if (vCodeTokens.length > 0 && iCodeTokens.length > 0) {
    const shared = sharedCodeTokens(vTokens, iTokens);
    const score = shared.length / Math.max(Math.min(vCodeTokens.length, iCodeTokens.length), 1);
    return { score, weight: 1.5 };
  }

  return { score: 0, weight: 0 };
}

/**
 * Slash-separated variant splitting: some product names encode several
 * variants in one cell ("EU 309 W/K" → "EU 309 W" + "EU 309 K"). Vendors are
 * inconsistent about the spacing/dash around that suffix cluster — "EU 309
 * W/K", "EY1511-K/W" (no space at all) and "EP4022 -K/W" (space before the
 * dash only, none after) all encode the same pattern — so this matches the
 * trailing run of short alphanumeric segments joined by "/" directly,
 * allowing (and discarding) any dash/space gluing it to the base, instead of
 * requiring the base and the suffix to already be their own whitespace
 * token. Which suffixes are valid is never predefined — only the structure
 * is checked — and an all-numeric cluster is left alone since that's a date
 * or a fraction, not a variant.
 */
export function splitSlashVariants(rawName: string): string[] {
  const name = rawName.trim();
  const m = name.match(/^(.*?)[\s-]*([\p{L}\p{N}]{1,6}(?:\/[\p{L}\p{N}]{1,6})+)\s*$/u);
  if (!m) return [name];
  const base = m[1].trim();
  if (!base) return [name]; // no shared base name before the variant cluster
  const segments = m[2].split("/");
  if (segments.every((s) => /^\d+$/.test(s))) return [name]; // all-numeric = date or fraction
  return segments.map((s) => `${base} ${s}`);
}

/**
 * Candidate expansion: one vendor product line may actually describe several
 * products (e.g. enumerated sizes separated by "/" or ","). The pattern is
 * detected from the raw value structure, never from a predefined product list.
 */
export function expandCandidates(rawValue: string): string[] {
  const raw = rawValue.trim();
  if (raw === "") return [];
  const results = new Set<string>([raw]);

  // pattern: enumerations like "A / B / C" or "A, B" where segments share a token class
  const enumMatch = raw.match(/([\p{L}\d.,]+(?:\s*[\/|]\s*[\p{L}\d.,]+)+)/u);
  if (enumMatch) {
    const segment = enumMatch[1];
    const parts = segment.split(/\s*[\/|]\s*/).filter((p) => p.length > 0);
    if (parts.length >= 2 && parts.length <= 8) {
      const classes = new Set(parts.map((p) => (/\d/.test(p) ? "num" : "word")));
      const shortish = parts.every((p) => p.length <= 12);
      if (classes.size === 1 && shortish) {
        for (const p of parts) {
          results.add(raw.replace(segment, p));
        }
      }
    }
  }
  return [...results];
}
