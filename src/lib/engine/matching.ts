import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { cleanValue } from "@/lib/engine/cleaning";
import { tokenize, buildIdf, expandCandidates, codeSimilarity, classifyToken } from "@/lib/engine/tokens";
import { weightedTokenSimilarity, diceCoefficient, levenshteinRatio, otsuThreshold } from "@/lib/engine/similarity";
import { chatCompletion } from "@/lib/chat/openrouter";
import type { MatchCandidate } from "@/lib/types";

export interface EngineRow {
  id: string;
  nameRaw: string;
  nameNorm: string;
  tokens: string[];
  code: string | null;
  variant: string | null;
  brand: string | null;
  description: string | null;
}

export interface SignalScores {
  name: number;
  compact: number;
  tokens: number;
  code: number;
  variant: number;
  brand: number;
  description: number;
}

/** Strip every space so spacing/segmentation differences never separate two identical names. */
const compactName = (s: string): string => s.replace(/\s+/g, "");

function toEngineRow(r: {
  id: string;
  nameRaw: string | null;
  nameNorm: string | null;
  tokens: string | null;
  code: string | null;
  variant: string | null;
  brand: string | null;
  data: string;
}): EngineRow {
  const data = safeJson<Record<string, string>>(r.data, {});
  return {
    id: r.id,
    nameRaw: r.nameRaw ?? "",
    nameNorm: r.nameNorm ?? "",
    tokens: safeJson<string[]>(r.tokens, []),
    code: r.code,
    variant: r.variant,
    brand: r.brand,
    description: data["description"] ?? null,
  };
}

/**
 * Composite similarity. Weights are renormalized over the signals that are
 * actually available for the pair — no fixed rule set, no fixed threshold.
 */
export function scorePair(v: EngineRow, i: EngineRow, idf: Map<string, number>): { score: number; signals: SignalScores } {
  const signals: SignalScores = { name: 0, compact: 0, tokens: 0, code: 0, variant: 0, brand: 0, description: 0 };
  const weights: Partial<Record<keyof SignalScores, number>> = {};

  signals.name = diceCoefficient(v.nameNorm, i.nameNorm) * 0.5 + levenshteinRatio(v.nameNorm, i.nameNorm) * 0.5;
  weights.name = 1.5;

  // Two names that are identical once spacing is stripped ("EU309 W" vs "EU 309W")
  // should score as near-identical — word segmentation varies per vendor, the
  // characters don't. This never replaces the token/name signals, it just
  // stops spacing quirks from diluting an otherwise exact match.
  const vCompact = compactName(v.nameNorm);
  const iCompact = compactName(i.nameNorm);
  if (vCompact && iCompact) {
    signals.compact = vCompact === iCompact ? 1 : levenshteinRatio(vCompact, iCompact);
    weights.compact = 1;
  }

  signals.tokens = weightedTokenSimilarity(v.tokens, i.tokens, idf);
  weights.tokens = 2.5;

  // Robust to asymmetric column layouts (e.g. internal has a dedicated Code
  // column, vendor embeds the code inside the product name instead).
  const codeSignal = codeSimilarity(v.code, v.tokens, i.code, i.tokens);
  if (codeSignal.weight > 0) {
    signals.code = codeSignal.score;
    weights.code = codeSignal.weight;
  }

  if (v.variant && i.variant) {
    signals.variant = diceCoefficient(cleanValue(v.variant, []), cleanValue(i.variant, []));
    weights.variant = 1;
  }
  if (v.brand && i.brand) {
    signals.brand = diceCoefficient(cleanValue(v.brand, []), cleanValue(i.brand, []));
    weights.brand = 0.75;
  }
  if (v.description && i.description) {
    const dv = tokenize(cleanValue(v.description, ["symbol"]));
    const di = tokenize(cleanValue(i.description, ["symbol"]));
    signals.description = weightedTokenSimilarity(dv, di, idf) * 0.8;
    weights.description = 0.5;
  }

  // Discriminator tokens disagreeing is a strong negative signal: numeric/
  // measure tokens (sizes differ) plus short (<=3 char) word tokens, since a
  // short trailing token on an otherwise-identical name is almost always a
  // variant/color/finish marker (e.g. "F-EU309-W" vs "F-EU309-K" — the W/K
  // IS the whole difference; "FV-10EGK216" vs "FV-10EGS216" — the EGK/EGS
  // infix is). These short tokens are exactly the kind IDF downweights
  // globally (they're common across the whole catalog), so without this
  // they barely register even though locally, among near-duplicate
  // siblings, they're the only thing that actually distinguishes the right
  // SKU from the wrong one. Ordinary short words (like "FAN") agree across
  // every candidate in the same category, so this only ever penalizes
  // genuine disagreement, never the shared vocabulary.
  const isDiscriminatorToken = (t: string) => {
    const cls = classifyToken(t);
    return cls === "numeric" || cls === "measure" || cls === "code" || (cls === "word" && t.length <= 3);
  };
  const vDisc = v.tokens.filter(isDiscriminatorToken);
  const iDisc = i.tokens.filter(isDiscriminatorToken);
  let discriminatorPenalty = 0;
  if (vDisc.length > 0 && iDisc.length > 0) {
    const setI = new Set(iDisc);
    const overlap = vDisc.filter((t) => setI.has(t)).length;
    const agree = overlap / Math.max(Math.min(vDisc.length, iDisc.length), 1);
    discriminatorPenalty = (1 - agree) * 0.35;
  }

  let totalW = 0;
  let sum = 0;
  for (const key of Object.keys(weights) as (keyof SignalScores)[]) {
    const w = weights[key] ?? 0;
    totalW += w;
    sum += signals[key] * w;
  }
  const score = Math.max(0, Math.min(1, (totalW === 0 ? 0 : sum / totalW) - discriminatorPenalty));
  return { score, signals };
}

/** Small inverted index over informative tokens to avoid O(n*m) full scan. */
function buildIndex(rows: EngineRow[]): Map<string, number[]> {
  const index = new Map<string, number[]>();
  rows.forEach((r, pos) => {
    for (const t of new Set(r.tokens)) {
      const arr = index.get(t);
      if (arr) arr.push(pos);
      else index.set(t, [pos]);
    }
  });
  return index;
}

interface AiVerdict {
  matched: boolean;
  candidateIndex: number | null; // 1-based index into the candidate list offered to the model
  reason: string;
}

/**
 * Second-stage validation for a fuzzy-ambiguous match: asks an LLM to judge whether the
 * vendor line and the engine's top candidates describe the same product, weighing product
 * code/variant/spec rather than raw text similarity. Generic across every vendor/category -
 * the candidate list and product names are the only input, nothing is predefined.
 * Best-effort: any failure (timeout, unparseable reply, all models down) returns null and the
 * caller keeps the engine's own NEED_REVIEW classification, never blocks the run.
 */
async function validateMatchWithAI(vendorLabel: string, vendorCode: string | null, candidates: MatchCandidate[]): Promise<AiVerdict | null> {
  if (candidates.length === 0) return null;
  const list = candidates
    .map((c, i) => `${i + 1}. "${c.label}"${c.code ? ` (code: ${c.code})` : ""} — fuzzy score ${c.score.toFixed(2)}`)
    .join("\n");
  const prompt = `You are validating a product price-audit match between a vendor's price list line and a company's internal product catalog.

Vendor line: "${vendorLabel}"${vendorCode ? ` (code: ${vendorCode})` : ""}

Internal catalog candidates:
${list}

Decide whether the vendor line refers to the SAME product as one of the candidates above. Compare product type code, variant/color/finish suffix and specifications - not just text similarity (the fuzzy scores above are already known to be unreliable on their own here, that's why you're being asked). Two rows that differ only in variant letter (e.g. "-W" vs "-K") or in size/capacity are NOT the same product.

Reply with ONLY a single-line JSON object, no other text: {"match": true or false, "candidate": <1-based number from the list above, or null if none match>, "reason": "<one short sentence>"}`;

  try {
    const { content } = await chatCompletion([{ role: "user", content: prompt }]);
    const jsonText = content.match(/\{[\s\S]*\}/)?.[0];
    if (!jsonText) return null;
    const parsed = JSON.parse(jsonText);
    if (typeof parsed.match !== "boolean") return null;
    const idx = typeof parsed.candidate === "number" ? parsed.candidate : null;
    return {
      matched: parsed.match,
      candidateIndex: idx !== null && idx >= 1 && idx <= candidates.length ? idx : null,
      reason: typeof parsed.reason === "string" ? parsed.reason : "",
    };
  } catch {
    return null;
  }
}

/** Runs `fn` over `items` with at most `limit` in flight at once - no queue library needed for this. */
async function mapWithConcurrency<T, R>(items: T[], limit: number, fn: (item: T, index: number) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i], i);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

export interface MatchRunStats {
  total: number;
  matched: number;
  partial: number;
  needReview: number;
  unmatched: number;
  fromMaster: number;
  thresholdHigh: number;
  thresholdLow: number;
}

export async function runMatching(jobId: string, sessionId: string): Promise<void> {
  const session = await prisma.matchSession.findUniqueOrThrow({ where: { id: sessionId } });
  const setProgress = async (progress: number, message: string) => {
    await prisma.job.update({ where: { id: jobId }, data: { progress, message } });
  };

  await setProgress(2, "Loading datasets");
  const [vendorRows, internalRows, vendorDataset] = await Promise.all([
    prisma.dataRow.findMany({ where: { datasetId: session.vendorDatasetId } }),
    prisma.dataRow.findMany({ where: { datasetId: session.internalDatasetId } }),
    prisma.dataset.findUniqueOrThrow({ where: { id: session.vendorDatasetId } }),
  ]);

  const vRows = vendorRows.map(toEngineRow);
  const iRows = internalRows.map(toEngineRow);

  await setProgress(8, "Analyzing token corpus");
  const idf = buildIdf([...vRows, ...iRows].map((r) => r.tokens));
  const index = buildIndex(iRows);

  await setProgress(12, "Loading master mapping (learning engine)");
  const vendorName = vendorDataset.vendorName ?? "";
  const masters = await prisma.masterMapping.findMany({
    where: { OR: [{ vendorName }, { vendorName: "" }] },
  });
  const masterByKey = new Map<string, (typeof masters)[number]>();
  for (const m of masters) {
    // vendor-specific mapping takes precedence over the generic one
    const existing = masterByKey.get(m.vendorKey);
    if (!existing || (existing.vendorName === "" && m.vendorName !== "")) masterByKey.set(m.vendorKey, m);
  }
  const internalByKey = new Map<string, EngineRow>();
  for (const r of iRows) internalByKey.set(r.nameNorm, r);

  interface Prelim {
    vendorRowId: string;
    internalRowId: string | null;
    score: number;
    margin: number;
    candidates: MatchCandidate[];
    signals: SignalScores | null;
    fromMaster: boolean;
  }
  const prelims: Prelim[] = [];

  for (let vi = 0; vi < vRows.length; vi++) {
    const v = vRows[vi];
    if (vi % 25 === 0) {
      await setProgress(12 + (vi / Math.max(vRows.length, 1)) * 70, `Matching ${vi + 1}/${vRows.length}`);
    }

    // 1) learning engine: approved master mapping wins immediately
    const master = masterByKey.get(v.nameNorm);
    if (master) {
      const hit = internalByKey.get(master.internalKey);
      if (hit) {
        prelims.push({
          vendorRowId: v.id,
          internalRowId: hit.id,
          score: 1,
          margin: 1,
          candidates: [{ rowId: hit.id, label: hit.nameRaw, code: hit.code, score: 1 }],
          signals: null,
          fromMaster: true,
        });
        continue;
      }
    }

    // 2) candidate generation: the vendor line itself may expand into several candidate products
    const expansions = expandCandidates(v.nameRaw);
    const variants: EngineRow[] =
      expansions.length > 1
        ? expansions.map((raw) => {
            const norm = cleanValue(raw, ["dash", "slash", "paren", "symbol", "dupword"]);
            return { ...v, nameRaw: raw, nameNorm: norm, tokens: tokenize(norm) };
          })
        : [v];

    // 3) gather internal candidates via inverted token index
    const counter = new Map<number, number>();
    for (const variant of variants) {
      for (const t of new Set(variant.tokens)) {
        const positions = index.get(t);
        if (!positions) continue;
        const w = idf.get(t) ?? 1;
        for (const p of positions) counter.set(p, (counter.get(p) ?? 0) + w);
      }
    }
    const candidatePositions = [...counter.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 60)
      .map(([p]) => p);

    let best: { row: EngineRow; score: number; signals: SignalScores } | null = null;
    let second = 0;
    const scored: MatchCandidate[] = [];
    for (const p of candidatePositions) {
      const i = iRows[p];
      let pairBest: { score: number; signals: SignalScores } | null = null;
      for (const variant of variants) {
        const res = scorePair(variant, i, idf);
        if (!pairBest || res.score > pairBest.score) pairBest = res;
      }
      if (!pairBest) continue;
      scored.push({ rowId: i.id, label: i.nameRaw, code: i.code, score: Number(pairBest.score.toFixed(4)) });
      if (!best || pairBest.score > best.score) {
        second = best?.score ?? 0;
        best = { row: i, score: pairBest.score, signals: pairBest.signals };
      } else if (pairBest.score > second) {
        second = pairBest.score;
      }
    }
    scored.sort((a, b) => b.score - a.score);

    prelims.push({
      vendorRowId: v.id,
      internalRowId: best?.row.id ?? null,
      score: best?.score ?? 0,
      margin: best ? best.score - second : 0,
      candidates: scored.slice(0, 5),
      signals: best?.signals ?? null,
      fromMaster: false,
    });
  }

  await setProgress(85, "Computing dynamic thresholds");
  // Dynamic classification: thresholds derived from this run's score distribution (Otsu),
  // never a fixed magic number.
  const engineScores = prelims.filter((p) => !p.fromMaster).map((p) => p.score);
  const tHigh = Math.max(otsuThreshold(engineScores, 0.65), 0.4);
  const lowScores = engineScores.filter((s) => s < tHigh);
  const tLow = Math.min(Math.max(otsuThreshold(lowScores, tHigh * 0.5), 0.15), tHigh * 0.85);
  const marginValues = prelims.filter((p) => !p.fromMaster && p.margin > 0).map((p) => p.margin);
  const marginMean = marginValues.length ? marginValues.reduce((a, b) => a + b, 0) / marginValues.length : 0.1;

  const classify = (p: Prelim): string => {
    if (p.fromMaster) return "MATCHED";
    if (p.score >= tHigh && p.margin >= marginMean * 0.5) return "MATCHED";
    if (p.score >= tHigh) return "NEED_REVIEW"; // strong score but ambiguous (competitor too close)
    if (p.score >= tLow) return p.margin < marginMean * 0.35 ? "NEED_REVIEW" : "PARTIAL";
    return "UNMATCHED";
  };

  // Hybrid stage 2: fuzzy screening above already produced a score for every vendor line;
  // only the ones it left ambiguous (NEED_REVIEW) go to the LLM, so token spend scales with
  // how much the fuzzy stage actually struggled, not with catalog size.
  // ponytail: fixed cap + concurrency - revisit if a vendor file regularly needs more AI calls
  // than this covers (the excess just keeps its engine-only NEED_REVIEW classification).
  const AI_VALIDATION_CAP = 60;
  const aiCandidates = prelims.filter((p) => classify(p) === "NEED_REVIEW" && p.candidates.length > 0).slice(0, AI_VALIDATION_CAP);
  const aiVerdicts = new Map<string, AiVerdict>();
  if (aiCandidates.length > 0) {
    await setProgress(87, `AI validation 0/${aiCandidates.length} ambiguous matches`);
    let done = 0;
    await mapWithConcurrency(aiCandidates, 4, async (p) => {
      const v = vRows.find((r) => r.id === p.vendorRowId);
      const verdict = v ? await validateMatchWithAI(v.nameRaw, v.code, p.candidates) : null;
      done++;
      if (done % 5 === 0 || done === aiCandidates.length) {
        await setProgress(87 + (done / aiCandidates.length) * 3, `AI validation ${done}/${aiCandidates.length} ambiguous matches`);
      }
      if (verdict) aiVerdicts.set(p.vendorRowId, verdict);
    });
  }

  const stats: MatchRunStats = {
    total: prelims.length,
    matched: 0,
    partial: 0,
    needReview: 0,
    unmatched: 0,
    fromMaster: 0,
    thresholdHigh: Number(tHigh.toFixed(3)),
    thresholdLow: Number(tLow.toFixed(3)),
  };

  await setProgress(90, "Saving results");
  const creates = prelims.map((p) => {
    let status = classify(p);
    let internalRowId = p.internalRowId;
    let source = p.fromMaster ? "MASTER" : "ENGINE";
    let aiNote: string | null = null;

    if (status === "NEED_REVIEW") {
      const verdict = aiVerdicts.get(p.vendorRowId);
      if (verdict) {
        source = "AI";
        aiNote = verdict.reason;
        if (verdict.matched && verdict.candidateIndex !== null) {
          status = "MATCHED";
          internalRowId = p.candidates[verdict.candidateIndex - 1].rowId;
        } else {
          status = "UNMATCHED";
        }
      }
    }

    if (status === "MATCHED") stats.matched++;
    else if (status === "PARTIAL") stats.partial++;
    else if (status === "NEED_REVIEW") stats.needReview++;
    else stats.unmatched++;
    if (p.fromMaster) stats.fromMaster++;

    const confidence = p.fromMaster
      ? 1
      : source === "AI"
        ? status === "MATCHED"
          ? 0.75
          : 0.25
        : Math.max(0, Math.min(1, p.score * (0.6 + 0.4 * Math.min(1, p.margin / Math.max(marginMean, 0.001)))));
    const detail = aiNote ? JSON.stringify({ ...(p.signals ?? {}), aiReason: aiNote }) : p.signals ? JSON.stringify(p.signals) : null;
    return {
      sessionId,
      vendorRowId: p.vendorRowId,
      internalRowId: status === "UNMATCHED" ? null : internalRowId,
      score: Number(p.score.toFixed(4)),
      confidence: Number(confidence.toFixed(4)),
      status,
      source,
      candidates: JSON.stringify(p.candidates),
      detail,
    };
  });

  const chunk = 500;
  await prisma.$transaction([
    prisma.matchResult.deleteMany({ where: { sessionId } }),
    ...Array.from({ length: Math.ceil(creates.length / chunk) }, (_, i) =>
      prisma.matchResult.createMany({ data: creates.slice(i * chunk, i * chunk + chunk) })
    ),
  ]);

  await prisma.matchSession.update({
    where: { id: sessionId },
    data: { status: "COMPLETED", stats: JSON.stringify(stats) },
  });
  await prisma.job.update({
    where: { id: jobId },
    data: { status: "COMPLETED", progress: 100, message: "Completed", result: JSON.stringify(stats) },
  });
}
