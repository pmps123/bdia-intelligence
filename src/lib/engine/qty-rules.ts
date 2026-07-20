import { parseNumeric } from "../parse/file-parser";

/**
 * Customized Price quantity gradation.
 * Rules are interpreted from the uploaded data itself (Qty Rule / From / To
 * columns in any combination) — no quantity value or range is ever assumed.
 */

export interface QtyRange {
  min: number | null; // inclusive
  max: number | null; // inclusive, null = open-ended
  label: string;
}

/** Parse one row's quantity rule out of whatever fields the file provides. */
export function parseQtyRule(rule: string | null | undefined, from: string | null | undefined, to: string | null | undefined): QtyRange | null {
  const r = (rule ?? "").trim();
  const fromN = parseNumeric(from);
  const toN = parseNumeric(to);

  // numbers may be embedded in the rule text itself (">= 10", "5 - 9", "between 5 and 9")
  const nums = (r.match(/\d+(?:[.,]\d+)?/g) ?? []).map((x) => parseNumeric(x)).filter((x): x is number => x !== null);

  if (/>=/.test(r) || /^>\s*=?/.test(r) || /min/i.test(r)) {
    const strict = /^>\s*\d/.test(r) && !/>=/.test(r);
    const base = nums[0] ?? fromN;
    if (base === null) return null;
    const min = strict ? base + 1 : base;
    return { min, max: null, label: `>= ${min}` };
  }
  if (/<=/.test(r) || /^<\s*=?/.test(r) || /max/i.test(r)) {
    const strict = /^<\s*\d/.test(r) && !/<=/.test(r);
    const base = nums[0] ?? toN ?? fromN;
    if (base === null) return null;
    const max = strict ? base - 1 : base;
    return { min: null, max, label: `<= ${max}` };
  }
  if (/between|antara/i.test(r) || nums.length >= 2) {
    const min = nums[0] ?? fromN;
    const max = nums[1] ?? toN;
    if (min === null && max === null) return null;
    return { min, max, label: max === null ? `>= ${min}` : `${min ?? 0} - ${max}` };
  }
  // a bare "5 - 9" style range without keywords
  if (/^\s*\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?\s*$/.test(r) && nums.length === 2) {
    return { min: nums[0], max: nums[1], label: `${nums[0]} - ${nums[1]}` };
  }
  // no usable rule text — fall back to the From / To columns alone
  if (fromN !== null || toN !== null) {
    if (fromN !== null && toN !== null) return { min: fromN, max: toN, label: `${fromN} - ${toN}` };
    if (fromN !== null) return { min: fromN, max: null, label: `>= ${fromN}` };
    return { min: null, max: toN, label: `<= ${toN}` };
  }
  return null;
}

/** Does a quantity fall inside a parsed range? */
export function qtyInRange(qty: number, min: number | null, max: number | null): boolean {
  if (min !== null && qty < min) return false;
  if (max !== null && qty > max) return false;
  return true;
}
