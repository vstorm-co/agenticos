import type { SVGProps } from "react";

import { GlyphIcon } from "@/components/icons/glyph";
import { BRAND_GLYPHS, type BrandName } from "@/lib/brand-glyphs.generated";

/** Brand glyphs from the maintained icon sets, checked in by
 *  `scripts/gen-brand-icons.ts` - never hand-authored SVG paths, so the marks
 *  stay correct and recognizable. Monochrome (currentColor) so they inherit the
 *  surrounding text color. A mark this set lacks is added to the generator's
 *  table and fetched, not written out here. */

export type { BrandName };

interface BrandIconProps extends SVGProps<SVGSVGElement> {
  name: BrandName;
}

export function BrandIcon({ name, "aria-label": ariaLabel, ...props }: BrandIconProps) {
  // Decorative by default - paired with a text label in our layouts. Pass
  // `aria-label` explicitly to make it semantic (e.g. icon-only buttons).
  const a11y = ariaLabel ? { role: "img", "aria-label": ariaLabel } : { "aria-hidden": true };
  return <GlyphIcon glyph={BRAND_GLYPHS[name]} {...a11y} {...props} />;
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
