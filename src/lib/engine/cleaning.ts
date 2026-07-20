import type { CleaningReport, CleaningRule } from "@/lib/types";

/**
 * Dynamic cleaning engine.
 * No cleaning rule is hardcoded against any specific product or vendor:
 * the engine inspects the uploaded values, detects which noise classes are
 * actually present (invisible chars, symbols, duplicate words, case mix, ...)
 * and only then generates + applies the normalization pipeline.
 */

const INVISIBLE_RE = /[\p{Cf}\p{Cc}]/gu;
const SYMBOL_RE = /[^\p{L}\p{N}\s.,+%]/gu;
const MULTI_SPACE_RE = /\s{2,}/g;

interface DetectorSpec {
  id: string;
  label: string;
  description: string;
  test: (v: string) => boolean;
}

const DETECTORS: DetectorSpec[] = [
  { id: "invisible", label: "Invisible characters", description: "Zero-width / control characters removed", test: (v) => /[\p{Cf}\p{Cc}]/u.test(v) },
  { id: "unicode", label: "Unicode normalization", description: "Full-width & compatibility characters normalized (NFKC)", test: (v) => v !== v.normalize("NFKC") },
  { id: "multispace", label: "Repeated spaces", description: "Runs of whitespace collapsed to a single space", test: (v) => /\s{2,}/.test(v) },
  { id: "trim", label: "Leading/trailing spaces", description: "Surrounding whitespace trimmed", test: (v) => v !== v.trim() },
  { id: "dash", label: "Dashes", description: "Dashes treated as separators", test: (v) => /[-–—]/.test(v) },
  { id: "slash", label: "Slashes", description: "Slashes treated as separators", test: (v) => /[\/\\]/.test(v) },
  { id: "paren", label: "Parentheses / brackets", description: "Bracket characters treated as separators", test: (v) => /[()\[\]{}]/.test(v) },
  { id: "symbol", label: "Symbols", description: "Non-alphanumeric symbols stripped", test: (v) => { SYMBOL_RE.lastIndex = 0; return SYMBOL_RE.test(v.replace(/[-–—\/\\()\[\]{}]/g, "")); } },
  { id: "case", label: "Mixed casing", description: "Values case-folded for comparison", test: (v) => /[a-z]/.test(v) && /[A-Z]/.test(v) },
  { id: "dupword", label: "Duplicate words", description: "Consecutive duplicate words de-duplicated", test: (v) => /\b(\S+)\s+\1\b/i.test(v) },
];

export function analyzeCleaning(values: string[]): CleaningReport {
  const sample = values.filter((v) => v && v.trim() !== "").slice(0, 5000);
  const rules: CleaningRule[] = [];
  for (const d of DETECTORS) {
    let count = 0;
    for (const v of sample) {
      try {
        if (d.test(v)) count++;
      } catch {
        // ignore detector failure on odd input
      }
    }
    if (count > 0) rules.push({ id: d.id, label: d.label, description: d.description, occurrences: count });
  }
  return { rules, sampleSize: sample.length };
}

/** Normalize a value using only the rule set generated for this dataset. */
export function cleanValue(value: string, activeRuleIds: string[]): string {
  let v = value ?? "";
  const has = (id: string) => activeRuleIds.includes(id);

  if (has("unicode")) v = v.normalize("NFKC");
  if (has("invisible")) v = v.replace(INVISIBLE_RE, "");
  if (has("dash")) v = v.replace(/[-–—]/g, " ");
  if (has("slash")) v = v.replace(/[\/\\]/g, " ");
  if (has("paren")) v = v.replace(/[()\[\]{}]/g, " ");
  if (has("symbol")) v = v.replace(SYMBOL_RE, " ");
  v = v.replace(MULTI_SPACE_RE, " ").trim();
  if (has("case")) v = v.toUpperCase();
  else v = v.toUpperCase(); // comparison is always case-insensitive
  if (has("dupword")) {
    const words = v.split(" ");
    const out: string[] = [];
    for (const w of words) {
      if (out.length === 0 || out[out.length - 1] !== w) out.push(w);
    }
    v = out.join(" ");
  }
  return v;
}
