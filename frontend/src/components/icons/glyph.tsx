import type { SVGProps } from "react";

import type { Glyph } from "@/lib/brand-glyphs.generated";

interface GlyphIconProps extends SVGProps<SVGSVGElement> {
  glyph: Glyph;
}

/**
 * A brand mark from `brand-glyphs.generated.ts`, as an `<svg>`.
 *
 * The one thing that turns generated path data into a rendered mark, so
 * `BrandIcon` and `ProviderIcon` draw identically rather than agreeing by
 * accident. Always `currentColor`: the console's marks are monochrome and
 * inherit the surrounding text colour, which is also what makes them survive a
 * dark surface without a second palette.
 *
 * Sized `1em` like the icon libraries this replaced, so a caller that sizes with
 * `h-4 w-4` still wins - a CSS dimension beats an SVG presentation attribute -
 * and one that sizes with the font still gets the old behaviour.
 */
export function GlyphIcon({ glyph, ...props }: GlyphIconProps) {
  return (
    <svg
      viewBox={glyph.viewBox}
      fill="currentColor"
      fillRule={glyph.fillRule}
      width="1em"
      height="1em"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      {glyph.paths.map((path) => (
        <path key={path.d} d={path.d} fillOpacity={path.fillOpacity} />
      ))}
    </svg>
  );
}
