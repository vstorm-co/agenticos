"use client";

import { RoutinePermissions } from "./routine-permissions";

import { LocalAgentSettings } from "./local-agent-settings";
import { LocalServiceSettings } from "./local-service-settings";

import { Laptop, Link2, Unlink } from "lucide-react";
import { useTranslations } from "next-intl";

import { DesktopOnly } from "@/components/desktop/desktop-only";
import { SectionCard } from "@/components/settings/settings-section";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
  Badge,
  Button,
} from "@/components/ui";
import { useDeviceLink, useDeviceStatus } from "@/hooks/use-desktop";
import { DIALOG_CONFIRM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";

/**
 * This computer as a place the person's own agents can work (#2305): linked once,
 * then reachable whenever the app runs. What it may do is chosen per chat - the
 * folder and the mode - so this card only says whether the door is there.
 */
export function DeviceSettings() {
  const t = useTranslations("desktop.settings.device");
  const { data: status } = useDeviceStatus();
  const { link, unlink } = useDeviceLink();
  return (
    <DesktopOnly>
      {() => (
        <>
          <SectionCard title={t("title")} description={t("description")}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-foreground flex items-center gap-2 text-sm">
                <Laptop className="text-muted-foreground h-4 w-4" aria-hidden />
                {!status?.linked
                  ? t("notLinked")
                  : status.connected
                    ? t("connected")
                    : t("reconnecting")}
                {status?.linked && status.connected && (
                  <Badge variant="secondary">{t("live")}</Badge>
                )}
              </span>
              {status?.linked ? (
                <UnlinkButton pending={unlink.isPending} onConfirm={() => unlink.mutate()} />
              ) : (
                <Button size="sm" disabled={link.isPending} onClick={() => link.mutate()}>
                  <Link2 className="h-4 w-4" />
                  {t("link")}
                </Button>
              )}
            </div>
          </SectionCard>
          <RoutinePermissions />

          <LocalAgentSettings />
          <LocalServiceSettings />
        </>
      )}
    </DesktopOnly>
  );
}

const CLEARED = ["folders", "services", "consents", "routines", "sessions"] as const;

/** Unlinking forgets everything this computer was allowed, so it asks first and says what. */
function UnlinkButton({ pending, onConfirm }: { pending: boolean; onConfirm: () => void }) {
  const t = useTranslations("desktop.settings.device");
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={pending}>
          <Unlink className="h-4 w-4" />
          {t("unlink")}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent className={cn(DIALOG_CONFIRM, DIALOG_SCROLL)}>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("unlinkTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("unlinkBody")}</AlertDialogDescription>
        </AlertDialogHeader>
        <ul className="text-muted-foreground list-disc space-y-1 pl-5 text-sm">
          {CLEARED.map((key) => (
            <li key={key}>{t(`unlinkClears.${key}`)}</li>
          ))}
        </ul>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("unlinkCancel")}</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>{t("unlinkConfirm")}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
