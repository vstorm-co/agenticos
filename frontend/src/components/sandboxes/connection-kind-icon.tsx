"use client";

import { Cloud } from "lucide-react";

import { BrandIcon } from "@/components/icons/brand-icon";
import type { SandboxConnectionKind } from "@/lib/sandbox-connections-api";
import { cn } from "@/lib/utils";

/**
 * What kind of host a connection is, as a mark.
 *
 * One place, because there are three surfaces that name a connection - the
 * dialog's `Kind`, the Builder's `Runs on`, the connections table - and a mark
 * chosen twice is a mark that will differ once.
 *
 * Docker's own, from the generated set. Daytona has none in any source the
 * generator reads - neither Simple Icons nor lobehub ships one - and a mark that
 * is not the brand's is worse than a neutral glyph, so it gets a cloud.
 */
export function ConnectionKindIcon({
  kind,
  className,
}: {
  kind: SandboxConnectionKind;
  className?: string;
}) {
  if (kind === "docker") {
    return <BrandIcon name="docker" className={cn("h-4 w-4 shrink-0", className)} aria-hidden />;
  }
  return <Cloud className={cn("text-muted-foreground h-4 w-4 shrink-0", className)} aria-hidden />;
}
