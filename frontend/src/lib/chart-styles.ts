/** Recharts draws inline SVG/HTML: use semantic colors, never series colors for text. */
export const CHART_TOOLTIP_CONTENT = {
  background: "var(--color-popover)",
  color: "var(--color-popover-foreground)",
  border: "1px solid var(--color-border)",
  borderRadius: 12,
  fontSize: 13,
  lineHeight: 1.5,
  padding: "10px 12px",
  boxShadow: "0 8px 24px rgb(0 0 0 / 0.16)",
} as const;
export const CHART_TOOLTIP_LABEL = {
  color: "var(--color-muted-foreground)",
  marginBottom: 4,
  fontSize: 12,
} as const;
export const CHART_TOOLTIP_ITEM = {
  color: "var(--color-popover-foreground)",
  fontWeight: 500,
  fontVariantNumeric: "tabular-nums",
} as const;
