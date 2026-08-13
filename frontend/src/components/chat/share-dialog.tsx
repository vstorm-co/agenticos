"use client";

import { useEffect, useState } from "react";
import { getErrorMessage } from "@/lib/api-error";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { Copy, Link2, Loader2, Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useTranslations } from "next-intl";
import { useConversationShares, useMembers } from "@/hooks";
import { useOrgStore } from "@/stores";
import type { ConversationShare, OrganizationMember } from "@/types";

interface ShareDialogProps {
  conversationId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * The members whose email or name contains the query, for the typeahead.
 *
 * An exact match is not a suggestion - the field already says it - and the cap
 * keeps the list a shortlist rather than the members page in a dropdown.
 */
export function matchingMembers(
  members: readonly OrganizationMember[],
  query: string,
  limit = 6,
): OrganizationMember[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  return members
    .filter(
      (member) =>
        member.email.toLowerCase() !== needle &&
        (member.email.toLowerCase().includes(needle) ||
          (member.full_name?.toLowerCase().includes(needle) ?? false)),
    )
    .slice(0, limit);
}

export function ShareDialog({ conversationId, open, onOpenChange }: ShareDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("chat");
  const { shares, isLoading, shareConversation, fetchShares, revokeShare } =
    useConversationShares();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members } = useMembers(activeOrgId ?? "");
  const [email, setEmail] = useState("");
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [permission, setPermission] = useState<"view" | "edit">("view");
  const [shareLink, setShareLink] = useState<string | null>(null);
  const { copy, copied } = useCopyToClipboard();
  const [isSharing, setIsSharing] = useState(false);
  const [isGeneratingLink, setIsGeneratingLink] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const suggestions = matchingMembers(members, email);

  useEffect(() => {
    if (open && conversationId) {
      fetchShares(conversationId);
    }
  }, [open, conversationId, fetchShares]);

  const handleShare = async () => {
    if (!email.trim()) return;
    setIsSharing(true);
    try {
      await shareConversation(conversationId, {
        shared_with_email: email.trim(),
        permission,
      });
      setEmail("");
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
        permission,
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("shareConversationTitle")}</DialogTitle>
          <DialogDescription>{t("shareDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <Input
                type="email"
                placeholder={t("memberEmail")}
                aria-label={t("memberEmail")}
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setSuggestionsOpen(true);
                }}
                onFocus={() => setSuggestionsOpen(true)}
                onBlur={() => setSuggestionsOpen(false)}
                onKeyDown={(e) => e.key === t("enter8") && handleShare()}
              />
              {suggestionsOpen && suggestions.length > 0 && (
                <div
                  role="listbox"
                  aria-label={t("memberSuggestions")}
                  className="border-border bg-popover absolute top-full right-0 left-0 z-50 mt-1 overflow-hidden rounded-md border shadow-md"
                >
                  {suggestions.map((member) => (
                    <button
                      key={member.user_id}
                      type="button"
                      role="option"
                      aria-selected={false}
                      // onMouseDown, so the pick lands before the input's blur
                      // closes the list.
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setEmail(member.email);
                        setSuggestionsOpen(false);
                      }}
                      className="hover:bg-accent w-full px-3 py-2 text-left"
                    >
                      <span className="block truncate text-sm">{member.email}</span>
                      {member.full_name && (
                        <span className="text-muted-foreground block truncate text-xs">
                          {member.full_name}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <Select value={permission} onValueChange={(v) => setPermission(v as "view" | "edit")}>
              <SelectTrigger className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="view">{t("view")}</SelectItem>
                <SelectItem value="edit">{t("edit")}</SelectItem>
              </SelectContent>
            </Select>
            <Button
              onClick={handleShare}
              disabled={isLoading || isSharing}
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

          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={handleGenerateLink}
              disabled={isLoading || isGeneratingLink}
              className="flex-1"
            >
              {isGeneratingLink ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Link2 className="mr-2 h-4 w-4" />
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
          {shareLink && (
            <p className="text-muted-foreground text-xs break-all">
              {copied ? t("copied") : shareLink}
            </p>
          )}

          {shares.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("sharedWith")}</p>
              {shares.map((share) => (
                <div
                  key={share.id}
                  className="flex items-center justify-between rounded-md border p-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm">
                      {share.shared_with_email || share.shared_with || t("link")}
                    </span>
                    <Badge variant="secondary">{share.permission}</Badge>
                    {share.share_token && <Badge variant="outline">{t("link")}</Badge>}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRevoke(share)}
                    disabled={revokingId === share.id}
                    className="h-8 w-8"
                    aria-label={t("revokeAccess")}
                  >
                    {revokingId === share.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
