"use client";

import { Sparkles } from "lucide-react";

import { useBranding } from "@/components/branding/branding-provider";
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
    <span
      aria-hidden
      title={appName}
      className={cn(
        "bg-foreground text-background inline-flex shrink-0 items-center justify-center rounded-md",
        className,
      )}
      style={{ width: size, height: size }}
      data-testid="brand-glyph"
    >
      <Sparkles style={{ width: size * 0.58, height: size * 0.58 }} />
    </span>
  );
}
