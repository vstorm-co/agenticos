"use client";

import { Box, KeyRound, TrainFront, type LucideIcon } from "lucide-react";

import { CustomMark, useCustomIcons } from "@/components/icons/custom-icons";
import { GlyphIcon } from "@/components/icons/glyph";
import { Monogram } from "@/components/icons/monogram";
import { BRAND_GLYPHS, PROVIDER_GLYPHS, type BrandName } from "@/lib/brand-glyphs.generated";
import { cn } from "@/lib/utils";

/**
 * What a service with no brand mark anywhere is drawn as: what it does.
 *
 * Neither Simple Icons nor the lobehub set carries Daytona, and the
 * platform's own sandbox service and a custom key are not brands at all. A
 * bordered initial for each read as unfinished rows in a vault
 * whose other rows wear real marks, so these wear the console's own icon for
 * the job instead - never a hand-drawn logo, which is the generator's rule.
 */
const SERVICE_MARKS: Readonly<Record<string, LucideIcon>> = {
  custom: KeyRound,
  sandboxd: Box,
  daytona: Box,
  e2b: Box,
  // No icon set carries LiteLLM; its own mark is the bullet-train emoji.
  litellm: TrainFront,
};

/** Every provider id with a mark - what the monochrome pin in the test iterates. */
export const MARKED_PROVIDERS: readonly string[] = Object.keys(PROVIDER_GLYPHS);

interface ProviderIconProps {
  /** The catalog id, e.g. `openai` or `google_cloud`. */
  provider: string;
  /**
   * The mark the catalog named for this entry, when its id is not one.
   *
   * A model provider's id *is* a glyph key, which is why the lookup below works
   * at all. A service's is not: `github_oauth_app` names a credential, not a
   * brand, so the vault's picker drew a `G` monogram for GitHub, `L` for
   * LlamaParse and `S` for the sandbox service - four rows of initials in a
   * product whose every other list wears real marks. The catalog says which mark
   * instead of this file keeping a second mapping to forget.
   */
  brand?: string;
  className?: string;
}

/**
 * A provider's logo: the checked-in mark, a custom mark the deployment ships
 * under this id, or a monogram.
 *
 * A provider can have no brand mark anywhere - LiteLLM has none, and wears the
 * service mark above - and a deployment gains a provider whenever
 * Pydantic AI does - so the missing case is the normal case, not the error
 * case. The middle step is a deployment's answer to it: drop `heroku.svg`
 * into the backend's catalog icons and this draws it, as a `currentColor`
 * silhouette that keeps the monochrome register. The monogram remains the
 * floor - a bordered initial reads as deliberate; a blank gap does not.
 *
 * **Why every mark is monochrome, including brands that have a colour form.**
 * The console's brand marks are `currentColor` - the MCP catalog, the connectors
 * and the sign-in buttons all draw that way - and a column where Gemini is four
 * colours while OpenAI is ink reads as two different UIs. Monochrome also
 * follows the theme for free; a colour mark has to hope its palette survives a
 * dark surface. `gen-brand-icons.ts` refuses a source path with a literal fill,
 * and `provider-icon.test.tsx` pins every mark to it.
 *
 * Always decorative. Every place this is used prints the provider beside it,
 * and an icon that repeated the name would make a screen reader say it twice.
 */
export function ProviderIcon({ provider, brand, className }: ProviderIconProps) {
  const custom = useCustomIcons();
  const glyph = (brand && BRAND_GLYPHS[brand as BrandName]) || PROVIDER_GLYPHS[provider];
  const size = cn("h-5 w-5 shrink-0", className);

  if (glyph) return <GlyphIcon glyph={glyph} aria-hidden className={size} />;
  if (custom.has(provider)) return <CustomMark name={provider} className={size} />;
  const ServiceMark = SERVICE_MARKS[provider];
  if (ServiceMark) return <ServiceMark aria-hidden className={cn(size, "text-foreground")} />;

  return <Monogram label={provider} className={size} />;
}
