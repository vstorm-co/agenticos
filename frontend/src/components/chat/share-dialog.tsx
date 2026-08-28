"use client";

import { useEffect, useMemo, useState } from "react";
import { Copy, Eye, Link2, Loader2, Pencil, Trash2, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { MemberIdentity, displayName } from "@/components/orgs/member-identity";
import type { IdentifiedMember } from "@/components/orgs/member-identity";
import { MemberPicker } from "@/components/orgs/member-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConversationShares, useMembers } from "@/hooks";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useAuthStore, useOrgStore } from "@/stores";
import type { ConversationShare } from "@/types";

interface ShareDialogProps {
  conversationId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Permission = "view" | "edit";

/**
 * What each level looks like, and the order they are offered in.
 *
 * An icon per level in both places it is read - the picker and each row of the
 * access list - because "edit" on a conversation is not self-evident: it carries
 * renaming, archiving, deleting the thread and appending turns, which
 * `ConversationService._may_write` decides and nothing on this dialog used to
 * say. The word is the permission's own catalog key.
 */
const LEVELS: readonly Permission[] = ["view", "edit"];
const LEVEL_ICONS: Record<Permission, typeof Eye> = { view: Eye, edit: Pencil };

/** Radix hands back a plain string; a level the catalog does not know is a bug. */
export function toPermission(value: string): Permission {
  // i18n-exempt: a bug in the caller, never shown to a reader
  if (value !== "view" && value !== "edit") {
    // i18n-exempt: the same
    throw new Error(`Unknown conversation permission: ${value}`);
  }
  return value;
}

/**
 * The person a share names, drawn as this application draws a person.
 *
 * Resolved against the organization's members first, so the row carries the face
 * and the name rather than only the address. A share whose member is gone still
 * has to be revocable, so it falls back to whatever the row itself holds - which
 * is the address for a share made by email, and the id otherwise.
 */
export function sharedPerson(
  share: ConversationShare,
  members: readonly IdentifiedMember[],
): IdentifiedMember | null {
  if (share.share_token) return null;
  const known = members.find((member) => member.user_id === share.shared_with);
  if (known) return known;
  const email = share.shared_with_email ?? share.shared_with;
  return email === undefined ? null : { user_id: share.shared_with ?? share.id, email };
}

function LevelBadge({ permission }: { permission: Permission }) {
  const t = useTranslations("chat");
  const Icon = LEVEL_ICONS[permission];
  return (
    <Badge variant="secondary" className="gap-1">
      <Icon className="h-3 w-3" aria-hidden />
      {t(permission)}
    </Badge>
  );
}

/**
 * Sharing one conversation: with a person, or by link.
 *
 * Who it is shared with is **picked**, never typed. The product's member picker
 * is a popover over a `cmdk` list - open it and the organization is there, each
 * row a face and a name over the address - where this dialog had an email field
 * with a hand-rolled suggestion list that appeared only once something had been
 * typed. So the default state of the control was a blank box you had to already
 * know the answer to fill, and every mistyped address was a 404 (#931).
 *
 * The API takes the id the picker holds: `shared_with` has always been accepted
 * beside `shared_with_email`, so this is a client change rather than a contract
 * one - and it removes the whole class of "no user with that email" refusals,
 * along with sharing outside the organization by construction (#930's client
 * half).
 *
 * The link half stays its own row, below a separator. A share token is not a
 * person: it has no face, no level to read against a name, and putting it in the
 * same row as one made both harder to read.
 */
export function ShareDialog({ conversationId, open, onOpenChange }: ShareDialogProps) {
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const t = useTranslations("chat");
  const { shares, isLoading, shareConversation, fetchShares, revokeShare } =
    useConversationShares();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const currentUserId = useAuthStore((state) => state.user?.id);
  const { members, error: membersError, fetchMembers } = useMembers(activeOrgId ?? "");
  const [picked, setPicked] = useState<string | null>(null);
  const [permission, setPermission] = useState<Permission>("view");
  const [shareLink, setShareLink] = useState<string | null>(null);
  const { copy, copied } = useCopyToClipboard();
  const [isSharing, setIsSharing] = useState(false);
  const [isGeneratingLink, setIsGeneratingLink] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  // Somebody who already has access is not a candidate, and neither is the
  // reader: offering either is a row that answers "already shared" or "cannot
  // share with yourself" after the click rather than before it. Every option the
  // picker offers can succeed.
  const candidates = useMemo(() => {
    const already = new Set(shares.map((share) => share.shared_with));
    return members.filter(
      (member) => member.user_id !== currentUserId && !already.has(member.user_id),
    );
  }, [members, shares, currentUserId]);

  useEffect(() => {
    if (open && conversationId) {
      fetchShares(conversationId);
    }
  }, [open, conversationId, fetchShares]);

  const handleShare = async (userId: string) => {
    setIsSharing(true);
    try {
      await shareConversation(conversationId, { shared_with: userId, permission });
      setPicked(null);
      toast.success(t("conversationShared"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("failedToShare")));
    } finally {
      setIsSharing(false);
    }
  };

  const handleGenerateLink = async () => {
    setIsGeneratingLink(true);
    try {
      const share = await shareConversation(conversationId, {
        generate_link: true,
        // Always view, whatever the picker above says. A token reaches exactly
        // one route - `GET /conversations/shared/{token}` - so there is no
        // token-authorised write to grant, and an `edit` link would promise
        // renaming, archiving and appending that the surface cannot do (#931).
        permission: "view",
      });
      if (share?.share_token) {
        const url = `${window.location.origin}/shared/${share.share_token}`;
        setShareLink(url);
        toast.success(t("linkGenerated"));
      }
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("failedToGenerateLink")));
    } finally {
      setIsGeneratingLink(false);
    }
  };

  const handleCopyLink = async () => {
    if (shareLink) {
      await copy(shareLink);
      toast.success(t("copyLink"));
    }
  };

  const handleRevoke = async (share: ConversationShare) => {
    setRevokingId(share.id);
    try {
      await revokeShare(conversationId, share.id);
      toast.success(t("accessRevoked"));
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("failedToRevoke")));
    } finally {
      setRevokingId(null);
    }
  };

  // The chosen member rather than the id, and the difference matters while the
  // shares are being refetched: an answer that says somebody already has access
  // takes them out of `candidates`, and a button enabled on the id alone would
  // then submit a share the server refuses.
  const chosen = candidates.find((member) => member.user_id === picked);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("shareConversationTitle")}</DialogTitle>
          <DialogDescription>{t("shareDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <MemberPicker
                members={candidates}
                selected={picked === null ? [] : [picked]}
                onToggle={(userId) => setPicked((current) => (current === userId ? null : userId))}
                label={() => (chosen ? displayName(chosen) : t("choosePerson"))}
                scope={t("shareConversationTitle")}
                disabled={candidates.length === 0}
              />
              <Select value={permission} onValueChange={(v) => setPermission(toPermission(v))}>
                <SelectTrigger className="w-32" aria-label={t("accessLevel")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LEVELS.map((level) => {
                    const Icon = LEVEL_ICONS[level];
                    return (
                      <SelectItem key={level} value={level}>
                        <span className="flex items-center gap-2">
                          <Icon className="h-3.5 w-3.5" aria-hidden />
                          {t(level)}
                        </span>
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
              <Button
                // The narrowing *is* the guard: the button is disabled with
                // nobody picked, so a handler that re-checked would hold a
                // branch nothing can reach.
                onClick={chosen === undefined ? undefined : () => void handleShare(chosen.user_id)}
                disabled={isLoading || isSharing || chosen === undefined}
                size="icon"
                aria-label={t("shareConversationTitle")}
              >
                {isSharing ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <UserPlus className="h-4 w-4" aria-hidden />
                )}
              </Button>
            </div>
            {/* What the level actually permits, because "edit" on a thread is not
                obvious: it is rename, archive, delete and append. */}
            <p className="text-muted-foreground text-xs">
              {permission === "edit" ? t("editMeans") : t("viewMeans")}
            </p>
            {/* Said, because the picker is the only way to name somebody: a
                members request that failed would otherwise leave it empty and
                disabled with no explanation and nothing to press. */}
            {membersError !== null && (
              <p className="text-destructive flex flex-wrap items-center gap-2 text-xs">
                {t("membersCouldNotBeRead")}
                <Button variant="ghost" size="sm" onClick={() => fetchMembers()}>
                  {tc("retry")}
                </Button>
              </p>
            )}
          </div>

          {shares.length > 0 && (
            <div className="space-y-2 border-t pt-4">
              <p className="text-sm font-medium">{t("sharedWith")}</p>
              {shares.map((share) => {
                const person = sharedPerson(share, members);
                return (
                  <div
                    key={share.id}
                    className="flex items-center gap-3 rounded-md border p-2 pl-3"
                  >
                    {person ? (
                      <MemberIdentity member={person} className="min-w-0 flex-1" />
                    ) : (
                      <span className="flex min-w-0 flex-1 items-center gap-2.5 text-sm">
                        <Link2 className="h-4 w-4 shrink-0" aria-hidden />
                        {t("link")}
                      </span>
                    )}
                    <LevelBadge permission={share.permission} />
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleRevoke(share)}
                      disabled={revokingId === share.id}
                      className="h-8 w-8 shrink-0"
                      aria-label={t("revokeAccess")}
                    >
                      {revokingId === share.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : (
                        <Trash2 className="h-4 w-4" aria-hidden />
                      )}
                    </Button>
                  </div>
                );
              })}
            </div>
          )}

          <div className="space-y-2 border-t pt-4">
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={handleGenerateLink}
                disabled={isLoading || isGeneratingLink}
                className="flex-1"
              >
                {isGeneratingLink ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Link2 className="mr-2 h-4 w-4" aria-hidden />
                )}
                {t("generateShareLink")}
              </Button>
              {shareLink && (
                <Button
                  variant="secondary"
                  size="icon"
                  onClick={handleCopyLink}
                  aria-label={t("copyShareLink")}
                >
                  <Copy className="h-4 w-4" aria-hidden />
                </Button>
              )}
            </div>
            {/* Said before the link is minted, not after: the level chosen above
                is about a person, and a link is read-only whatever it says. */}
            <p className="text-muted-foreground text-xs">{t("linkIsViewOnly")}</p>
            {shareLink && (
              <p className="text-muted-foreground text-xs break-all">
                {copied ? t("copied") : shareLink}
              </p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
