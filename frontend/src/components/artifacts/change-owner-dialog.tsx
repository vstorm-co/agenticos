"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { displayName } from "@/components/orgs/member-identity";
import { encodeSubject } from "@/components/sharing/grants";
import { SubjectPicker } from "@/components/sharing/subject-picker";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
} from "@/components/ui";
import { useMembers } from "@/hooks";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { useOrgStore } from "@/stores";
import { useAuthStore } from "@/stores/auth-store";
import type { ArtifactDetail } from "@/types/artifact";

interface ChangeOwnerDialogProps {
  artifact: ArtifactDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Sends the change; `onDone` runs once the server took it - a refusal is the caller's to report. */
  onChangeOwner: (userId: string, onDone: () => void) => void;
  pending: boolean;
}

/**
 * Hands a page to another member: pick who, then a second step that says what it
 * does before anything is sent - the change is immediate, and the page's data stops
 * reaching its audience until the new owner confirms it.
 *
 * The picker is the one the Share dialog uses, members only; the current owner is
 * left out because the server refuses a page's owner as its new one. Rendered only
 * for a caller the server said may change the owner (`may_change_owner`).
 */
export function ChangeOwnerDialog({
  artifact,
  open,
  onOpenChange,
  onChangeOwner,
  pending,
}: ChangeOwnerDialogProps) {
  const t = useTranslations("artifacts.changeOwner");
  const activeOrgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { members } = useMembers(activeOrgId);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const [subject, setSubject] = useState("");
  const [confirming, setConfirming] = useState(false);
  const candidates = members.filter((member) => member.user_id !== artifact.owner_user_id);
  const chosen = candidates.find(
    (member) => encodeSubject({ kind: "user", id: member.user_id }) === subject,
  );
  // The second step is for a chosen member, so it holds one.
  // Whoever makes the switch is never told of it: the previous owner is, unless that is them.
  const previousOwnerNotified =
    artifact.owner_user_id !== null && artifact.owner_user_id !== userId;
  const review = confirming && chosen !== undefined ? chosen : null;

  function close(next: boolean) {
    onOpenChange(next);
    if (!next) {
      setSubject("");
      setConfirming(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("title", { title: artifact.title })}</DialogTitle>
          <DialogDescription>
            {review
              ? t(previousOwnerNotified ? "confirm" : "confirmSelf", { name: displayName(review) })
              : t("why")}
          </DialogDescription>
        </DialogHeader>
        {review === null && (
          <div className="space-y-2">
            <Label htmlFor="artifact-new-owner">{t("newOwner")}</Label>
            <SubjectPicker
              id="artifact-new-owner"
              members={candidates}
              groups={[]}
              value={subject}
              onChange={setSubject}
              placeholder={t("choose")}
            />
          </div>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            disabled={pending}
            onClick={() => (review ? setConfirming(false) : close(false))}
          >
            {review ? t("back") : t("cancel")}
          </Button>
          {review ? (
            <Button
              disabled={pending}
              onClick={() => onChangeOwner(review.user_id, () => close(false))}
            >
              {pending ? "…" : t("submit")}
            </Button>
          ) : (
            <Button disabled={!chosen} onClick={() => setConfirming(true)}>
              {t("continue")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
