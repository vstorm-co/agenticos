"use client";

import { Globe } from "lucide-react";

import { FileIcon } from "@/components/files";
import { BrandIcon } from "@/components/icons/brand-icon";
import { brandForUrl } from "@/lib/link-brands";
import { cn } from "@/lib/utils";

/**
 * What a source is, as one round mark: the file's kind for a knowledge base
 * passage, the service's own logo for a page on Notion or GitHub, a globe for
 * the rest of the web.
 *
 * Round and ringed like an agent's face, so a row of them stacks the way the
 * faces in the conversation list do.
 */
export function SourceMark({
  type,
  title,
  url,
  className,
}: {
  type: "rag" | "web";
  title: string;
  url?: string;
  className?: string;
}) {
  const brand = url ? brandForUrl(url) : null;
  return (
    <span
      aria-hidden
      className={cn(
        "bg-background border-foreground/12 ring-background inline-flex size-6 shrink-0 items-center justify-center rounded-full border ring-2",
        className,
      )}
    >
      {type === "rag" ? (
        <FileIcon name={title} className="h-3.5 w-3.5" />
      ) : brand ? (
        <BrandIcon name={brand} className="h-3.5 w-3.5" />
      ) : (
        <Globe className="text-muted-foreground h-3.5 w-3.5" />
      )}
    </span>
  );
}
