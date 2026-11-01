"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import dynamic from "next/dynamic";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Skeleton,
} from "@/components/ui";
import { DIALOG_BODY, DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { qk } from "@/lib/query-keys";

const McpServerList = dynamic(
  () => import("@/components/mcp/mcp-server-list").then((module) => module.McpServerList),
  { loading: () => <Skeleton className="h-40 w-full" /> },
);

/** The existing account setup flow, kept above the workflow's unsaved form. */
export function WorkflowConnectionsDialog({
  open,
  onOpenChange,
  catalogKey,
}: {
  open: boolean;
  catalogKey?: string;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("workflows");
  const client = useQueryClient();
  const close = () => {
    void client.invalidateQueries({ queryKey: qk.mcpConnections.all() });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent className={`${DIALOG_CANVAS} ${DIALOG_FILL}`}>
        <DialogHeader>
          <DialogTitle>{t("pickerConnectAccount")}</DialogTitle>
          <DialogDescription>{t("pickerConnectAccountHint")}</DialogDescription>
        </DialogHeader>
        <div className={DIALOG_BODY}>
          {open && (
            <McpServerList
              canManageOrganization
              initialServerKey={catalogKey}
              persistSelection={false}
            />
          )}
        </div>
        <DialogFooter>
          <Button onClick={close}>{t("nodeEditorDone")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
