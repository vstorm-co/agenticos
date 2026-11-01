"use client";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { cn } from "@/lib/utils";
import type { WorkflowApp } from "./apps";

/** Workflows draw service identity through the same icon cascade as the MCP catalog. */
export function WorkflowAppIcon({
  app,
  name,
  className,
  iconClassName,
}: {
  app: WorkflowApp;
  name: string;
  className?: string;
  iconClassName?: string;
}) {
  return (
    <span
      className={cn(
        "bg-muted/40 flex size-7 shrink-0 items-center justify-center rounded-lg",
        className,
      )}
    >
      <McpServerIcon
        icon={app.brand ?? app.icon}
        url={app.name === undefined && app.brand ? undefined : app.url}
        name={name}
        className={cn("size-5", iconClassName)}
      />
    </span>
  );
}
