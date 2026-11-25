"use client";

import { ExportResourceDialog } from "@/components/portability/resource-export-dialog";

export function ExportAgentDialog({
  agentId,
  ...props
}: {
  agentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return <ExportResourceDialog {...props} resourceId={agentId} rootKind="agent" />;
}
