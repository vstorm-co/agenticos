"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { SharingResourceType } from "@/types/sharing";
import { SharingPanel } from "./sharing-panel";

/**
 * Share, on a resource that already exists: who reaches it, changed in place.
 *
 * A skill, a knowledge base or a context file was shared once, in the dialog
 * that created it, and never again - somebody who made a skill for themselves
 * could not hand it to the organization or a group afterwards. This is the
 * agent page's Share button and panel, for any resource the sharing API
 * serves. Shown to everyone who can open the resource, so they can see who
 * else does; only `canManage` may change it.
 */
export function ShareResourceButton({
  resourceType,
  resourceId,
  name,
  canManage,
  className,
}: {
  resourceType: SharingResourceType;
  resourceId: string;
  /** What the dialog's title calls the resource. */
  name: string;
  canManage: boolean;
  className?: string;
}) {
  const t = useTranslations("sharing");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} className={className}>
        <UserPlus className="h-4 w-4" />
        {t("share")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className={cn(DIALOG_SCROLL, DIALOG_FORM)}>
          <DialogHeader>
            <DialogTitle>{t("shareNamed", { name })}</DialogTitle>
          </DialogHeader>
          <SharingPanel resourceType={resourceType} resourceId={resourceId} canManage={canManage} />
        </DialogContent>
      </Dialog>
    </>
  );
}
