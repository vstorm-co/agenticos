"use client";

import { Globe } from "lucide-react";

import { FileIcon } from "@/components/files";
import { LinkFavicon } from "./link-favicon";
import { cn } from "@/lib/utils";

/**
 * What a source is, as one round mark: the file's kind for a knowledge base
 * passage, the site's favicon for a web page, and a globe when no icon is available.
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
      ) : url ? (
        <LinkFavicon key={url} url={url} className="h-3.5 w-3.5" />
      ) : (
        <Globe className="text-muted-foreground h-3.5 w-3.5" />
      )}
    </span>
  );
}
