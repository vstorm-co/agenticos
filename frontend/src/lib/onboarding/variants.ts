/** Preview layouts share the same setup contracts and never grant extra authority. */
export const START_VARIANTS = ["conversation", "studio", "launchpad"] as const;
export type StartVariant = (typeof START_VARIANTS)[number];
export function startVariant(value: string | null): StartVariant | null {
  return START_VARIANTS.find((variant) => variant === value) ?? null;
}
