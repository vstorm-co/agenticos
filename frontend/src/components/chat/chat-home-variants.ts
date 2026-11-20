const variants = [
  "calm",
  "desk",
  "briefing",
  "spotlight",
  "shelf",
  "tabs",
  "timeline",
  "commands",
  "journal",
  "dock",
] as const;

export type ChatHomeVariant = (typeof variants)[number];

export function chatHomeVariant(value: string | null): ChatHomeVariant | undefined {
  if (!value) return undefined;
  if (/^(?:[1-9]|10)$/.test(value)) return variants[Number(value) - 1];
  return variants.find((variant) => variant === value);
}
