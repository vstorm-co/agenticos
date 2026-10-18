"use client";

import { Globe } from "lucide-react";
import { useState } from "react";

import { BrandIcon } from "@/components/icons/brand-icon";
import { brandForUrl } from "@/lib/link-brands";
import { cn } from "@/lib/utils";

/**
 * A site's own mark: the bundled logo for a service the console knows, the
 * site's `favicon.ico` for the rest, and a globe where it has none.
 *
 * The favicon is asked of the site the person is linking anyway, with no
 * referrer, so it learns nothing about where the link was written.
 */
export function LinkFavicon({ url, className }: { url: string; className?: string }) {
  const [missing, setMissing] = useState(false);
  const brand = brandForUrl(url);
  const size = cn("h-4 w-4 shrink-0", className);
  if (brand) return <BrandIcon name={brand} aria-hidden className={size} />;
  let origin: string | null = null;
  try {
    origin = new URL(url).origin;
  } catch {
    origin = null;
  }
  if (origin === null || missing) {
    return <Globe aria-hidden className={cn(size, "text-muted-foreground")} />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a remote icon of unknown size, not a page image
    <img
      src={`${origin}/favicon.ico`}
      alt=""
      aria-hidden
      referrerPolicy="no-referrer"
      loading="lazy"
      onError={() => setMissing(true)}
      className={cn(size, "rounded-[3px] object-contain")}
    />
  );
}
