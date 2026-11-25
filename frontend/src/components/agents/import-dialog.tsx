"use client";

import { ImportResourceDialog } from "@/components/portability/resource-import-dialog";

export function ImportAgentDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return <ImportResourceDialog {...props} rootKind="agent" />;
}
