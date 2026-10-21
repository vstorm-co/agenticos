import type { SVGProps } from "react";

import type { Glyph } from "@/lib/brand-glyphs.generated";

interface GlyphIconProps extends SVGProps<SVGSVGElement> {
  glyph: Glyph;
  /**
   * Draw it in the surrounding text colour instead of the brand's - for a mark
   * on a filled control, where a brand colour would fight the fill.
   */
  mono?: boolean;
}

/**
 * A brand mark from `brand-glyphs.generated.ts`, as an `<svg>`.
 *
 * The one thing that turns generated path data into a rendered mark, so
 * `BrandIcon` and `ProviderIcon` draw identically rather than agreeing by
 * accident. In the brand's own colour where the generator recorded one that
 * reads on both themes - a catalog of grey glyphs reads as one icon repeated -
 * and in `currentColor` otherwise, which is what keeps a black or white brand
 * visible on either surface. A mark drawn in several colours carries one per
 * path, and `mono` drops those too.
 *
 * Sized `1em` like the icon libraries this replaced, so a caller that sizes with
 * `h-4 w-4` still wins - a CSS dimension beats an SVG presentation attribute -
 * and one that sizes with the font still gets the old behaviour.
 */
export function GlyphIcon({ glyph, mono = false, ...props }: GlyphIconProps) {
  return (
    <svg
      viewBox={glyph.viewBox}
      fill={mono || glyph.color === undefined ? "currentColor" : glyph.color}
      fillRule={glyph.fillRule}
      width="1em"
      height="1em"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      {glyph.paths.map((path) => (
        <path
          key={path.d}
          d={path.d}
          fillOpacity={path.fillOpacity}
          fill={mono ? undefined : path.fill}
        />
      ))}
    </svg>
  );
}
