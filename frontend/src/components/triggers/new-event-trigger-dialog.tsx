"use client";

import { useTranslations } from "next-intl";

import { PortalCatalog } from "@/components/triggers/portal-catalog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

interface NewEventTriggerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * The default path to a new event trigger, from every entry point that has no
 * page to navigate to - the agent panel and the chat sidebar.
 *
 * It embeds the portal grid in place: picking a portal proceeds into
 * `PortalTriggerDialog` with its own agent picker, so no context is lost even from
 * the sidebar, and the raw source-and-secret form is demoted to the grid's
 * "Advanced: custom webhook" hatch rather than a default button. The two
 * permissions the grid should not decide for itself are resolved here - creating a
 * trigger needs `agents:run`, connecting the organization's account needs
 * `connections:manage` - and the cards hide the actions the caller may not use.
 */
export function NewEventTriggerDialog({ open, onOpenChange }: NewEventTriggerDialogProps) {
  const t = useTranslations("triggers");
  const { can } = usePermissions();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("newEventTitle")}</DialogTitle>
          <DialogDescription>{t("newEventDescription")}</DialogDescription>
        </DialogHeader>
        <PortalCatalog
          canRun={can(Perm.agentsRun)}
          canManageConnections={can(Perm.connectionsManage)}
        />
      </DialogContent>
    </Dialog>
  );
}
