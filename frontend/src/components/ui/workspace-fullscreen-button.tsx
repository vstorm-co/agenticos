"use client";

import { Maximize2, Minimize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function WorkspaceFullscreenButton({
  expanded,
  onToggle,
  className,
}: {
  expanded: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const t = useTranslations("common");
  const label = t(expanded ? "workspaceCollapse" : "workspaceExpand");
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={cn("md:hidden", className)}
      aria-label={label}
      title={label}
      onClick={onToggle}
    >
      {expanded ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
    </Button>
  );
}
