"use client";

import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import type { AgentEnvironment } from "@/types/agents";

interface PublishDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The number the new version will take: one past the newest published. */
  version: number;
  /** Every environment of the agent, so the dialog can say which ones move. */
  environments: AgentEnvironment[];
  publishing?: boolean;
  onConfirm: () => void | Promise<void>;
}

/**
 * What publishing is about to change, said before it happens.
 *
 * Publishing freezes the draft as a new version and moves exactly one pointer:
 * the default environment. A named environment somebody pinned - dev on v12, a
 * client held back on v9 - stays put, and an agent with pinned environments is
 * exactly the one where the button hides the most. So the dialog names the
 * version it will create, the environment that moves the moment it lands, and
 * the ones that deliberately do not. The first publish is the other silent
 * surprise: it creates the default environment, and the agent goes live with
 * no further step.
 */
export function PublishDialog({
  open,
  onOpenChange,
  version,
  environments,
  publishing,
  onConfirm,
}: PublishDialogProps) {
  const t = useTranslations("agents");
  const tUi = useTranslations("ui");
  const defaultEnvironment = environments.find((environment) => environment.is_default);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("publishDialogTitle", { version })}</DialogTitle>
          <DialogDescription>{t("publishFreezesDraft", { version })}</DialogDescription>
        </DialogHeader>
        <div className="text-muted-foreground space-y-1.5 text-sm">
          {/* Where this version lands, environment by environment. Publishing
              mints a version and moves only what asked to be moved, so the one
              question worth answering before the click is "what changes for
              people using this agent" - and for most agents the answer is
              nothing until somebody promotes. */}
          {defaultEnvironment === undefined ? (
            <p>{t("publishFirstCreatesProduction", { version })}</p>
          ) : (
            environments.map((environment) => (
              <p key={environment.id}>
                {environment.tracks_latest
                  ? t("publishMovesFollower", { name: environment.name, version })
                  : t("publishPinnedStays", {
                      name: environment.name,
                      version: environment.version,
                    })}
              </p>
            ))
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={publishing}>
            {tUi("cancel")}
          </Button>
          <Button disabled={publishing} onClick={() => void onConfirm()}>
            {publishing ? "…" : t("publishConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
