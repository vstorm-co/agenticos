import type { SVGProps } from "react";

import { GlyphIcon } from "@/components/icons/glyph";
import { cn } from "@/lib/utils";
import { BRAND_GLYPHS, type BrandName } from "@/lib/brand-glyphs.generated";

/** Brand glyphs from the maintained icon sets, checked in by
 *  `scripts/gen-brand-icons.ts` - never hand-authored SVG paths, so the marks
 *  stay correct and recognizable. Monochrome (currentColor) by default, so they
 *  inherit the surrounding text color. A mark this set lacks is added to the
 *  generator's table and fetched, not written out here. */

export type { BrandName };

interface BrandIconProps extends SVGProps<SVGSVGElement> {
  name: BrandName;
  /**
   * Draw it in the brand's own colour instead of inheriting the text colour.
   *
   * Off by default, and the default is the product's rule: a list, a table or a
   * run's steps draw every mark in ink, because a column where one logo is four
   * colours and the next is ink reads as two products rather than one set.
   *
   * Asked for where the mark is the *subject* rather than an ornament - a grid of
   * services offering to be connected, which somebody scans by logo. There it is
   * all of them or none: colouring the ones with a vivid brand and leaving the
   * near-black ones in ink is the same inconsistency by another route.
   *
   * **A caller that asks owes the mark a light background.** Brand colours are
   * published for a white page: GitHub's `#181717` is invisible on a dark one.
   * That is why `BrandTile` exists and why this prop is not simply on by default.
   */
  colored?: boolean;
}

export function BrandIcon({
  name,
  colored = false,
  "aria-label": ariaLabel,
  ...props
}: BrandIconProps) {
  // Decorative by default - paired with a text label in our layouts. Pass
  // `aria-label` explicitly to make it semantic (e.g. icon-only buttons).
  const a11y = ariaLabel ? { role: "img", "aria-label": ariaLabel } : { "aria-hidden": true };
  const glyph = BRAND_GLYPHS[name];
  // `color`, not `fill`: the paths are drawn in `currentColor`, so setting the
  // text colour is what a caller can still override with a class if it needs to.
  const paint = colored && glyph.color !== undefined ? { color: glyph.color } : undefined;
  return <GlyphIcon glyph={glyph} style={paint} {...a11y} {...props} />;
}

/**
 * A `BrandIcon` bound to one mark, so a lookup table can hold brand marks and
 * lucide icons side by side and every entry is called the same way.
 *
 * Both channel and surface tables mix the two - Slack's mark next to a lucide
 * speech bubble for the dashboard - and a table of two shapes is a table with a
 * `typeof` in the middle of its renderer.
 */
export function brandMark(name: BrandName) {
  // `name` is omitted rather than shadowed: SVG elements carry one too, so a
  // caller spreading generic svg props could otherwise replace the mark with a
  // string and silently render nothing.
  return function Mark(props: Omit<SVGProps<SVGSVGElement>, "name">) {
    return <BrandIcon name={name} {...props} />;
  };
}

/**
 * Connector types, as the backend spells them, to the mark that shows one.
 *
 * More than one spelling reaches the same product: the registry key is
 * `gdrive`, older rows carry `google_drive`, and `aws` and `s3` are the same
 * bucket. Kept in one place because every surface that lists a sync source
 * needs the mapping, and three copies of it is how one of them ends up showing
 * a generic database icon for Drive.
 */
const CONNECTOR_BRANDS: Record<string, BrandName> = {
  google_drive: "gdrive",
  gdrive: "gdrive",
  drive: "gdrive",
  github: "github",
  notion: "notion",
  slack: "slack",
  dropbox: "dropbox",
  s3: "s3",
  aws: "s3",
};

/** The brand mark for a connector type, or `undefined` when it has none. */
export function connectorBrand(connectorType: string): BrandName | undefined {
  return CONNECTOR_BRANDS[connectorType];
}

/** Whether a catalog's icon name is one this set actually draws. */
export function isBrandName(value: string): value is BrandName {
  return value in BRAND_GLYPHS;
}

/**
 * A brand mark on the background its colour was chosen for.
 *
 * Brand palettes are published for a white page - GitHub's is `#181717`, Notion's
 * is near-black - so a coloured mark on this product's dark theme is a mark that
 * disappears. The tile is a fixed near-white square in both themes, which is what
 * every other product's integration grid does and for this reason.
 *
 * The alternative was colouring only the brands whose hue survives a dark
 * background, which is how Gmail ended up red beside a black GitHub: correct per
 * mark, wrong as a set.
 */
export function BrandTile({ name, className }: { name: BrandName; className?: string }) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md border border-black/5 bg-white",
        className,
      )}
      aria-hidden
    >
      <BrandIcon name={name} colored className="h-[62%] w-[62%]" />
    </span>
  );
}
