"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CopyButton } from "@/components/chat/copy-button";
import { useAssignableRoles, useInvitations, useRoleCatalog } from "@/hooks";
import { defaultAssignable } from "@/lib/assignable-roles";
import type { InvitationCreated, OrgRole } from "@/types";
import { useTranslations } from "next-intl";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

interface InviteMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
}

export function InviteMemberDialog({ open, onOpenChange, orgId }: InviteMemberDialogProps) {
  const t = useTranslations("teams");
  const [email, setEmail] = useState("");
  const [chosen, setChosen] = useState<OrgRole | "">("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Held here and nowhere else. The link is a bearer credential, so it is not
  // cached, not refetchable and not in the listing - this is the only copy
  // anybody gets, which is why the dialog stays open holding it rather than
  // closing on success the way it used to (#1479).
  const [sent, setSent] = useState<InvitationCreated | null>(null);
  const { invite } = useInvitations(orgId);
  const assignable = useAssignableRoles();
  // Said rather than left to an empty picker: a catalog that failed to load and
  // a caller who may assign nothing are the same pixels (#1028).
  const { error: rolesError } = useRoleCatalog();
  // The picker starts on Member where this caller may offer it, and never on a
  // role their own does not outrank - a value the list does not hold renders an
  // empty trigger and submits what the server refuses (#1028).
  const role = chosen === "" ? defaultAssignable(assignable, "member") : chosen;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || role === "") return;
    setIsSubmitting(true);
    const result = await invite({ email: email.trim(), role });
    setIsSubmitting(false);
    if (result) setSent(result);
  };

  const close = () => {
    onOpenChange(false);
    // After the dialog is gone, not during: clearing while it is still on screen
    // swaps the link for the empty form in front of whoever is reading it.
    setEmail("");
    setChosen("");
    setSent(null);
  };

  const acceptUrl = sent ? `${window.location.origin}/invitations/${sent.invitation_token}` : "";

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{sent ? t("inviteReady") : t("inviteMember")}</DialogTitle>
        </DialogHeader>
        {sent ? (
          <div className="space-y-4">
            <p className="text-muted-foreground text-sm">
              {sent.email_delivered
                ? t("inviteEmailed", { email: sent.email ?? "" })
                : t("inviteNotEmailed", { email: sent.email ?? "" })}
            </p>
            <div className="space-y-1.5">
              <Label htmlFor="invite-link">{t("inviteLinkLabel")}</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="invite-link"
                  readOnly
                  value={acceptUrl}
                  onFocus={(e) => e.currentTarget.select()}
                  className="font-mono text-xs"
                />
                <CopyButton text={acceptUrl} />
              </div>
              <p className="text-muted-foreground text-xs">{t("inviteLinkOnce")}</p>
            </div>
            <DialogFooter>
              <Button type="button" onClick={close}>
                {t("done")}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <FormField label={t("emailAddress")} htmlFor="invite-email">
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("colleagueExampleCom")}
                autoFocus
              />
            </FormField>
            <div className="space-y-1.5">
              <Label htmlFor="invite-role">{t("role")}</Label>
              {rolesError ? (
                <p className="text-destructive text-sm">{t("rolesUnavailable")}</p>
              ) : (
                <Select value={role} onValueChange={(v) => setChosen(v as OrgRole)}>
                  <SelectTrigger id="invite-role" className="capitalize">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {assignable.map((option) => (
                      <SelectItem key={option} value={option} className="capitalize">
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                {t("cancel3")}
              </Button>
              <Button type="submit" disabled={!email.trim() || role === "" || isSubmitting}>
                {isSubmitting ? t("sending2") : t("sendInvite")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
