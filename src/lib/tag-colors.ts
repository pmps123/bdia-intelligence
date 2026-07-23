/**
 * Fixed tag palette for Select/Status/Person columns — Notion-style colored pills. Deliberately
 * muted to sit inside the app's navy/red identity rather than a saturated rainbow: each color is
 * a tinted-neutral background with a matching dark-enough foreground for 4.5:1+ contrast.
 */
export const TAG_COLOR_KEYS = ["slate", "navy", "red", "amber", "green", "teal", "purple", "pink"] as const;
export type TagColorKey = (typeof TAG_COLOR_KEYS)[number];

export const TAG_COLOR_STYLES: Record<TagColorKey, { bg: string; text: string }> = {
  slate: { bg: "#e4e8ee", text: "#3b4656" },
  navy: { bg: "#dbe6f0", text: "#17385a" },
  red: { bg: "#f8dcdc", text: "#8a1c1e" },
  amber: { bg: "#faf0d2", text: "#7a5b12" },
  green: { bg: "#dcefe1", text: "#2c5f3f" },
  teal: { bg: "#d7f0ee", text: "#155e56" },
  purple: { bg: "#e8e0f7", text: "#4b3184" },
  pink: { bg: "#fbdfe9", text: "#8a2050" },
};

/** Auto-assign the next color in rotation — same behavior as Notion assigning a color the moment you create a new tag. */
export function nextTagColor(usedCount: number): TagColorKey {
  return TAG_COLOR_KEYS[usedCount % TAG_COLOR_KEYS.length];
}
