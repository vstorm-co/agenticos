"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "@/lib/api-error";
import { useChanged } from "@/hooks/use-changed";
import { Copy, KeyRound, Mail, Shield, ShieldOff, Trash2, UserX } from "lucide-react";
import { toast } from "sonner";

import { LoadingState } from "@/components/states";
import { EntityAvatar } from "@/components/ui/entity-avatar";
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
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import type { AdminUser } from "@/types";
import { apiClient } from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useLocale, useTranslations } from "next-intl";

interface UserDetailDrawerProps {
  user: AdminUser | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdate: (userId: string, patch: Partial<AdminUser>) => void;
  onDelete: (userId: string) => void;
  onImpersonate: (userId: string) => Promise<string | null | undefined>;
}

interface ConversationStub {
  id: string;
  title?: string | null;
  created_at: string;
  message_count?: number;
}

export function UserDetailDrawer({
  user,
  open,
  onOpenChange,
  onUpdate,
  onDelete,
  onImpersonate,
}: UserDetailDrawerProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("admin");
  const locale = useLocale();
  const currentUserId = useAuthStore((state) => state.user?.id);
  // Server data through the query layer, which is where `.claude/rules/frontend.md`
  // says it lives. It was three pieces of state and an effect: a list, a loading
  // flag, and a reset when the drawer closed - all of which `useQuery` already
  // has, including not firing at all while `enabled` is false.
  const {
    data: conversations = null,
    isPending: convsLoading,
    error: convsError,
  } = useQuery({
    queryKey: qk.admin.conversations({ userId: user?.id, limit: 8 }),
    queryFn: () =>
      apiClient
        .get<{ items: ConversationStub[] }>(`/admin/conversations?user_id=${user!.id}&limit=8`)
        .then((d) => d.items),
    enabled: open && Boolean(user),
  });

  // The row the drawer is showing, kept for as long as the sheet is on screen.
  //
  // The page holds the selected user's *id* and derives the row from the list,
  // so deleting one takes the row out from under an open drawer: `user` becomes
  // null while Radix is still animating the sheet closed, and returning null
  // here tore it out mid-slide. Holding the last one it was given lets the
  // animation finish showing what was deleted, which is what the user asked to
  // look at.
  const [shown, setShown] = useState(user);
  if (useChanged(user) && user) setShown(user);
  const subject = user ?? shown;

  if (!subject) return null;

  // Your own row does not offer Suspend, Demote or Impersonate: suspending or
  // demoting yourself ends your administration of the deployment (#941), and
  // impersonating yourself is meaningless. Delete stays visible and is refused
  // by the API, because "why can I not delete myself" has an answer worth showing.
  const isSelf = subject.id === currentUserId;

  const handleImpersonate = async () => {
    const token = await onImpersonate(subject.id);
    if (token) {
      try {
        await navigator.clipboard.writeText(token);
        toast.success(t("impersonationTokenCopiedValid"));
      } catch {
        toast.success(t("impersonationTokenCreated1h"));
      }
    }
  };

  const handleCopyId = async () => {
    try {
      await navigator.clipboard.writeText(subject.id);
      toast.success(t("userIdCopied"));
    } catch {
      toast.error(t("copyFailed"));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {/* The same drawer dialect as the run detail: SheetHeader with the
          title and its close, the body scrolling under it, standard tokens. */}
      <SheetContent side="right" className="w-full sm:max-w-lg">
        <SheetHeader className="px-5">
          <SheetTitle className="flex min-w-0 items-center gap-3 text-sm">
            <EntityAvatar
              seed={subject.id}
              name={subject.full_name || subject.email}
              imageSrc={`/api/users/avatar/${subject.id}`}
              className="h-8 w-8 shrink-0 text-xs"
              ariaHidden
            />
            <span className="min-w-0">
              <span className="text-foreground block truncate">
                {subject.full_name || subject.email.split("@")[0]}
              </span>
              <span className="text-muted-foreground block truncate text-xs font-normal">
                {subject.email}
              </span>
            </span>
          </SheetTitle>
          <SheetClose onClick={() => onOpenChange(false)} />
        </SheetHeader>

        <div className="flex-1 scrollbar-thin overflow-y-auto p-5">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant={subject.is_active ? "default" : "secondary"} className="text-[10px]">
              {subject.is_active ? t("active") : t("suspended")}
            </Badge>
            {/* One privilege, so one badge. There used to be a second one
                printing `users.role`, which said "user" for every account on
                the deployment - including the ones that administered it. */}
            {subject.is_app_admin && (
              <Badge className="bg-brand text-brand-foreground border-transparent text-[10px]">
                <Shield className="mr-1 h-3 w-3" />
                {t("appAdmin")}
              </Badge>
            )}
          </div>

          <dl className="border-border divide-border mt-5 divide-y rounded-xl border">
            <KV label={t("userId")} value={subject.id} mono onCopy={handleCopyId} />
            <KV label={t("email")} value={subject.email} mono />
            {subject.full_name && <KV label={t("displayName")} value={subject.full_name} />}
            <KV label={t("joined")} value={formatDateTime(subject.created_at, locale)} />
          </dl>

          <section className="mt-7">
            <h3 className="text-foreground mb-3 text-sm font-semibold">
              {t("recentConversations")}
            </h3>
            {convsLoading ? (
              <LoadingState variant="skeleton-list" rows={3} />
            ) : convsError ? (
              // Not "No conversations." - a 502 and an account that has never
              // opened a chat are the same sentence, and an admin acting on the
              // second when it was the first is acting on nothing.
              <p className="text-destructive text-xs">
                {getErrorMessage(convsError, tErrors, t("couldnTLoadConversations"))}
              </p>
            ) : !conversations || conversations.length === 0 ? (
              <p className="text-muted-foreground text-xs">{t("noConversationsFound")}</p>
            ) : (
              <ul className="space-y-1">
                {conversations.map((c) => (
                  <li
                    key={c.id}
                    className="border-border bg-background flex items-center justify-between gap-2 rounded-lg border px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-foreground truncate text-xs font-medium">
                        {c.title || t("untitled")}
                      </p>
                      <p className="text-muted-foreground truncate text-xs">
                        {formatDateTime(c.created_at, locale)}
                        {typeof c.message_count === "number" &&
                          ` · ${t("messageCountShort", { count: c.message_count })}`}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <footer className="border-border flex flex-wrap items-center gap-2 border-t px-5 py-4">
          {!isSelf && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onUpdate(subject.id, { is_active: !subject.is_active })}
              >
                {subject.is_active ? (
                  <>
                    <UserX className="mr-1.5 h-3.5 w-3.5" />
                    {t("suspend")}
                  </>
                ) : (
                  <>
                    <Mail className="mr-1.5 h-3.5 w-3.5" />
                    {t("reactivate")}
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onUpdate(subject.id, { is_app_admin: !subject.is_app_admin })}
              >
                {subject.is_app_admin ? (
                  <>
                    <ShieldOff className="mr-1.5 h-3.5 w-3.5" />
                    {t("demote")}
                  </>
                ) : (
                  <>
                    <Shield className="mr-1.5 h-3.5 w-3.5" />
                    {t("promoteAdmin")}
                  </>
                )}
              </Button>
              <Button variant="outline" size="sm" onClick={handleImpersonate}>
                <KeyRound className="mr-1.5 h-3.5 w-3.5" />
                {t("impersonate")}
              </Button>
            </>
          )}

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive ml-auto"
              >
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                {t("delete")}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  {t("deleteUserNamed", { email: subject.email })}
                </AlertDialogTitle>
                <AlertDialogDescription>{t("permanentlyRemovesUserTheir")}</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => {
                    onDelete(subject.id);
                    onOpenChange(false);
                  }}
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  {t("deleteUser")}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </footer>
      </SheetContent>
    </Sheet>
  );
}

function KV({
  label,
  value,
  mono,
  onCopy,
}: {
  label: string;
  value: string;
  mono?: boolean;
  onCopy?: () => void;
}) {
  const t = useTranslations("admin");
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5">
      <dt className="text-muted-foreground text-xs tracking-wide uppercase">{label}</dt>
      <dd className="flex items-center gap-2">
        <span className={mono ? "text-foreground font-mono text-xs" : "text-foreground text-xs"}>
          {value}
        </span>
        {onCopy && (
          <button
            type="button"
            onClick={onCopy}
            className="text-muted-foreground hover:text-foreground inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors"
            title={t("copy")}
          >
            <Copy className="h-3 w-3" />
          </button>
        )}
      </dd>
    </div>
  );
}
