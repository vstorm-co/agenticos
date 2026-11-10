"use client";

import { useState } from "react";
import noticeStyles from "@/components/layout/account-notices.module.css";
import { usePathname, useRouter } from "next/navigation";
import { MailPlus, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { pageOf } from "@/lib/assistant-bubbles";
import { useChanged } from "@/hooks/use-changed";
import { useReceivedInvitations } from "@/hooks/use-received-invitations";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

/** Account-scoped offers, including people who have no organization yet. */
export function ReceivedInvitations() {
  const t = useTranslations("invitations.received");
  const userId = useAuthStore((state) =>
    state.isAuthenticated && !state.isLoading ? state.user?.id : undefined,
  );
  const mailboxProved = useAuthStore((state) => state.user?.email_verified === true);
  const pathname = pageOf(usePathname());
  const visible =
    !!userId &&
    mailboxProved &&
    !/^\/(login|register|auth|shared|invitations)(\/|$)/.test(pathname);
  const inbox = useReceivedInvitations(visible);
  const router = useRouter();
  const setOrg = useOrgStore((state) => state.setActiveOrgId);
  const [dismissedFor, setDismissedFor] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);
  if (useChanged(userId)) {
    setDismissedFor(undefined);
    setFailed(false);
  }
  const invitations = inbox.data ?? [];
  if (!visible) return null;
  if (!invitations.length) return null;
  const join = async (id: string) => {
    setFailed(false);
    try {
      const result = await inbox.accept.mutateAsync(id);
      const current = useAuthStore.getState();
      if (!current.isAuthenticated || current.user?.id !== userId) return;
      setDismissedFor(userId);
      setOrg(result.organization_id);
      router.push("/onboarding?welcome=1&entry=joined");
    } catch {
      if (useAuthStore.getState().user?.id !== userId) return;
      setFailed(true);
      toast.error(t("failed"));
      void inbox.refetch();
    }
  };
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        data-invitation-entry="true"
        className={`${noticeStyles.surface} ${noticeStyles.entry}`}
        onClick={() => setDismissedFor(undefined)}
      >
        <MailPlus size={16} aria-hidden />
        {t("open", { count: invitations.length })}
      </Button>
      <Dialog
        open={dismissedFor !== userId}
        onOpenChange={(open) => {
          if (!open) setDismissedFor(userId);
        }}
      >
        <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
          <div className="mb-2 flex size-12 items-center justify-center rounded-2xl bg-violet-500/15 text-violet-400">
            <MailPlus size={24} aria-hidden />
          </div>
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>{t("description")}</DialogDescription>
          </DialogHeader>
          <div className="my-5 grid gap-3">
            {invitations.map((invite) => (
              <div
                key={invite.id}
                className="border-border flex flex-wrap items-center gap-4 rounded-2xl border p-4"
              >
                <EntityAvatar
                  seed={invite.organization_id}
                  name={invite.organization_name}
                  imageSrc={`/api/invitations/received/${encodeURIComponent(invite.id)}/avatar`}
                  hasImage={invite.organization_has_avatar}
                  colorSlot={invite.organization_avatar_color}
                  className="size-11 shrink-0"
                  ariaHidden
                />
                <div className="min-w-0 flex-1">
                  <p className="font-medium break-words">{invite.organization_name}</p>
                  <p className="text-muted-foreground text-sm">
                    {t("role", {
                      role: t.has(`roles.${invite.role}`) ? t(`roles.${invite.role}`) : invite.role,
                    })}
                  </p>
                </div>
                <Button disabled={inbox.accept.isPending} onClick={() => void join(invite.id)}>
                  {t(
                    inbox.accept.isPending && inbox.accept.variables === invite.id
                      ? "joining"
                      : "join",
                  )}
                  <ArrowRight size={15} aria-hidden />
                </Button>
              </div>
            ))}
          </div>
          {inbox.hasNextPage && (
            <Button
              variant="outline"
              disabled={inbox.isFetchingNextPage}
              onClick={() => void inbox.fetchNextPage()}
            >
              {t("more")}
            </Button>
          )}
          {failed && (
            <p role="alert" className="text-destructive-ink mb-4 text-sm">
              {t("failed")}
            </p>
          )}
          <Button
            variant="ghost"
            disabled={inbox.accept.isPending}
            onClick={() => setDismissedFor(userId)}
          >
            {t("later")}
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
