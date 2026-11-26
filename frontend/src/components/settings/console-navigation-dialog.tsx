"use client";

import { useState } from "react";
import { PanelLeft, Settings2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useConsoleExperience } from "@/hooks/use-console-experience";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui";
import { ConsoleNavigationControls } from "./console-navigation-controls";

/** The sidebar and profile share the same membership-scoped navigation editor. */
export function ConsoleNavigationDialog({
  compact = false,
  sidebar = false,
}: {
  compact?: boolean;
  sidebar?: boolean;
}) {
  const t = useTranslations("consoleExperience.presentation");
  const experience = useConsoleExperience();
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const presentation = experience.data?.presentation;
  if (!presentation) return null;
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={
          sidebar
            ? compact
              ? "text-muted-foreground hover:text-foreground size-9 shrink-0 rounded-lg p-0"
              : "text-muted-foreground mx-3 mb-1 justify-start gap-2"
            : "gap-2"
        }
        aria-label={t("customizeNavigation")}
        title={compact ? t("customizeNavigation") : undefined}
        data-tour={sidebar ? "sidebar-navigation-customize" : "personal-console-navigation-open"}
        onClick={() => setOpen(true)}
      >
        {sidebar ? (
          <Settings2 className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
        ) : (
          <PanelLeft className="size-4 shrink-0" aria-hidden />
        )}
        {!compact && t("customizeNavigation")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!dirty && !experience.save.isPending) setOpen(next);
        }}
      >
        <DialogContent
          className="flex max-h-[85dvh] max-w-3xl flex-col overflow-hidden"
          dismissible={!dirty && !experience.save.isPending}
        >
          <DialogHeader data-tour="personal-console-navigation">
            <DialogTitle className="flex items-center gap-2">
              <PanelLeft className="size-5" aria-hidden />
              {t("personalTitle")}
            </DialogTitle>
            <DialogDescription>{t("personalHint")}</DialogDescription>
          </DialogHeader>
          <div className="flex min-h-0 flex-1 flex-col">
            <ConsoleNavigationControls
              key={`${experience.organizationId}-${experience.userId}`}
              showUnavailable={false}
              scrollable
              value={presentation.preferences.navigation}
              allowed={presentation.organization_navigation}
              inherited={presentation.navigation_default}
              disabled={experience.save.isPending}
              onDirtyChange={setDirty}
              onSave={(navigation, saved) =>
                experience.save.mutate({ console: { navigation } }, () => {
                  saved();
                  setDirty(false);
                  setOpen(false);
                })
              }
            />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
