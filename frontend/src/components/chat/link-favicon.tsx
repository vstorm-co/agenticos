"use client";

import { Globe } from "lucide-react";
import { useState } from "react";

import { BrandIcon } from "@/components/icons/brand-icon";
import { brandForUrl } from "@/lib/link-brands";
import { cn } from "@/lib/utils";

/** Known logos stay local; unknown-site icons use the credential-free fixed-service proxy. */
export function LinkFavicon({ url, className }: { url: string; className?: string }) {
  const [missingOrigin, setMissingOrigin] = useState<string | null>(null);
  const brand = brandForUrl(url);
  const size = cn("h-4 w-4 shrink-0", className);
  if (brand) return <BrandIcon name={brand} aria-hidden className={size} />;
  let origin: string | null = null;
  try {
    const parsed = new URL(url);
    origin = parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.origin : null;
  } catch {
    origin = null;
  }
  if (origin === null || missingOrigin === origin) {
    return <Globe aria-hidden className={cn(size, "text-muted-foreground")} />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a remote icon of unknown size, not a page image
    <img
      src={`/api/link-icon?host=${encodeURIComponent(new URL(origin).hostname)}`}
      alt=""
      aria-hidden
      referrerPolicy="no-referrer"
      loading="lazy"
      onError={() => setMissingOrigin(origin)}
      className={cn(size, "rounded-[3px] object-contain")}
    />
  );
}
