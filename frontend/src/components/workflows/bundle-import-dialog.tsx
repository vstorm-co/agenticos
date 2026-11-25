"use client";

import { useState } from "react";
import { ImportResourceDialog } from "@/components/portability/resource-import-dialog";
import { ImportWorkflowDialog } from "./import-dialog";

/** Keep older workflow files available while making selective bundles the normal import. */
export function WorkflowImportEntryDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [legacy, setLegacy] = useState(false);
  const close = (next: boolean) => {
    if (!next) setLegacy(false);
    onOpenChange(next);
  };
  return legacy ? (
    <ImportWorkflowDialog open={open} onOpenChange={close} />
  ) : (
    <ImportResourceDialog
      rootKind="workflow"
      open={open}
      onOpenChange={close}
      onLegacy={() => setLegacy(true)}
    />
  );
}
