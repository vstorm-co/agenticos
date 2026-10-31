"use client";

import { useState } from "react";
import { Mail, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { BrandIcon } from "@/components/icons/brand-icon";
import { Button, ConfirmDialog } from "@/components/ui";
import { useAppConnections } from "@/components/workflows/use-app-connections";
import { WorkflowConnectionsDialog } from "@/components/workflows/pickers/workflow-connections-dialog";
import { pickerSections, type AppAction } from "@/components/workflows/picker/groups";
import { appToolLabel } from "@/components/workflows/apps";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/** Platform delivery and a connected mailbox are different senders. Switching to
 * a mailbox uses its actual tool schema rather than guessing its arguments. */
export function EmailAccountSetup({
  nodeId,
  catalog,
}: {
  nodeId: string;
  catalog: NodeDefinition[];
}) {
  const t = useTranslations("workflows");
  const source = useAppConnections();
  const [connecting, setConnecting] = useState<string | null>(null);
  const [selected, setSelected] = useState<AppAction | null>(null);
  const replace = useWorkflowEditorStore((state) => state.useEmailAccount);
  const actions = pickerSections(catalog, source)
    .flatMap((section) => section.groups)
    .flatMap((group) => group.app?.actions ?? [])
    .filter((action) => ["gmail", "outlook"].includes(action.app.id) && /send/i.test(action.tool));
  return (
    <div className="mb-6 space-y-3 border-b pb-5">
      <p className="flex items-center gap-2 text-sm font-medium">
        <Mail className="size-4" aria-hidden />
        {t("emailSender")}
      </p>
      <p className="text-muted-foreground text-sm">{t("emailPlatformSender")}</p>
      {actions.map((action) => (
        <Button
          key={action.key}
          type="button"
          variant="outline"
          className="h-auto w-full justify-start py-2 text-left whitespace-normal"
          onClick={() => setSelected(action)}
        >
          <Mail className="size-4 shrink-0" aria-hidden />
          <span>
            {action.connectionName} · {appToolLabel(action.app, action.tool, t)}
          </span>
        </Button>
      ))}
      {source.canConnect && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setConnecting("google-workspace")}
          >
            <BrandIcon name="gmail" className="size-4" />
            <Plus className="size-3" aria-hidden />
            {t("emailConnectGmail")}
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setConnecting("ms-365")}>
            <BrandIcon name="microsoft" className="size-4" />
            <Plus className="size-3" aria-hidden />
            {t("emailConnectOutlook")}
          </Button>
        </div>
      )}
      {connecting !== null && (
        <WorkflowConnectionsDialog
          open
          catalogKey={connecting}
          onOpenChange={(open) => !open && setConnecting(null)}
        />
      )}
      <ConfirmDialog
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
        title={t("emailSwitchTitle")}
        description={t("emailSwitchHint")}
        confirmLabel={t("emailSwitchConfirm")}
        onConfirm={() => {
          if (selected)
            replace(nodeId, selected.definition.version, selected.connectionId, selected.tool);
          setSelected(null);
        }}
      />
    </div>
  );
}
