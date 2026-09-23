"use client";

import { useBranding } from "@/components/branding/branding-provider";
import { AMIGO_HEAD_DATA_URI } from "@/lib/amigo-head.generated";
import { cn } from "@/lib/utils";

/**
 * The deployment's mark: an uploaded image, or the built-in glyph.
 *
 * One component for both, because every place that draws the mark has to answer
 * the same question and would otherwise answer it differently - which is how the
 * sign-in header and the sidebar end up disagreeing about whether this
 * installation has a logo.
 *
 * `alt` is empty on purpose. The mark always sits beside the name in text, so
 * describing it again is a screen reader saying the product twice; the wrapper
 * that has no visible name passes its own label instead.
 */
export function BrandMark({ className, size = 24 }: { className?: string; size?: number }) {
  const { appName, logoUrl } = useBranding();

  if (logoUrl) {
    return (
      // An operator's upload, served through this app's proxy from bytes the API
      // holds. `next/image` would need the route in `remotePatterns` and would
      // re-encode a wordmark it has no size to optimise for.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={logoUrl}
        alt=""
        width={size}
        height={size}
        // `object-contain`: an operator's wordmark is rarely square, and cropping
        // somebody's logo to a circle is not a decision this component gets to make.
        className={cn("shrink-0 rounded-md object-contain", className)}
        style={{ width: size, height: size }}
        data-testid="brand-logo"
      />
    );
  }

  return (
    // Amigo, cropped to his head so he fits a square slot. An `<img>` on a data
    // URI rather than inline paths, because `icon.tsx` hands `next/og` that exact
    // string - one drawing is what keeps the browser tab and the sidebar showing
    // the same face.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={AMIGO_HEAD_DATA_URI}
      alt=""
      aria-hidden
      title={appName}
      width={size}
      height={size}
      className={cn("shrink-0", className)}
      // The drawing is 16 pixels wide, so it is exact at 16, 32, 48 and 64 and
      // interpolated everywhere else; `pixelated` keeps those edges hard instead
      // of smearing a sprite into a smudge.
      style={{ width: size, height: size, imageRendering: "pixelated" }}
      data-testid="brand-glyph"
    />
  );
}
