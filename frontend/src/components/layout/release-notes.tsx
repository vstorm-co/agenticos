"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { version } from "../../../package.json";
import { useAuthStore } from "@/stores/auth-store";
import { useReleaseNotesStore } from "@/stores/release-notes-store";
import { useCurrentRelease } from "@/hooks/use-current-release";
import { isNewerRelease } from "@/lib/releases";
import { MarkdownContent } from "@/components/chat/markdown-content";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui";

/** Public release notes after sign-in, once per account and installed version on this device. */
export function ReleaseNotes() {
  const userId = useAuthStore((s) => s.user?.id);
  return userId ? <AccountReleaseNotes key={userId} userId={userId} /> : null;
}
function AccountReleaseNotes({ userId }: { userId: string }) {
  const t = useTranslations("nav");
  const seen = useReleaseNotesStore((s) => s.acknowledged[userId]);
  const acknowledge = useReleaseNotesStore((s) => s.acknowledge);
  const unseen = seen === undefined || isNewerRelease(seen, version);
  const { data } = useCurrentRelease(unseen);
  const [open, setOpen] = useState(false);
  const release = data?.release;
  useEffect(() => {
    if (!unseen || !release || open) return;
    const tryOpen = () => {
      if (!document.querySelector('[role="dialog"], [role="alertdialog"], .driver-popover'))
        setOpen(true);
    };
    // Let onboarding/readiness take priority; show after its dialog is dismissed.
    const observer = new MutationObserver(tryOpen);
    const timer = setTimeout(() => {
      tryOpen();
      observer.observe(document.body, { childList: true, subtree: true });
    }, 800);
    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [unseen, release, open]);
  if (!release) return null;
  const close = () => {
    acknowledge(userId, version);
    setOpen(false);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <DialogContent className="flex max-h-[85dvh] max-w-2xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>{t("whatsNewTitle", { version })}</DialogTitle>
          <DialogDescription>{t("whatsNewDescription")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto py-2 pr-2">
          <MarkdownContent content={release.body} inertImages bareCode />
        </div>
        <DialogFooter>
          <a
            href={release.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground inline-flex min-h-9 items-center text-sm underline underline-offset-4 sm:mr-auto"
          >
            {t("viewRelease")}
          </a>
          <Button onClick={close}>{t("whatsNewDone")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
