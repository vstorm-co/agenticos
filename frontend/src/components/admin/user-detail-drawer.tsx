"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useChanged } from "@/hooks/use-changed";
import { ArrowUpRight, Copy, KeyRound, Mail, Shield, ShieldOff, Trash2, UserX } from "lucide-react";
import { toast } from "sonner";

import { LoadingState } from "@/components/states";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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
  SheetContent,
} from "@/components/ui";
import type { AdminUser } from "@/types";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { formatDateTime, getErrorMessage } from "@/lib/utils";
import { qk } from "@/lib/query-keys";
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
  const t = useTranslations("admin");
  const locale = useLocale();
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

  const initials = (subject.full_name || subject.email)
    .split(/[\s@]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="border-foreground/10 bg-card flex w-full max-w-md flex-col overflow-hidden p-0 sm:max-w-lg"
      >
        <header className="border-foreground/10 flex items-center gap-4 border-b px-6 py-5">
          <Avatar className="h-12 w-12 shrink-0">
            <AvatarImage src={`/api/users/avatar/${subject.id}`} alt={subject.email} />
            <AvatarFallback className="font-mono text-sm">{initials || "?"}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="text-foreground truncate text-base font-semibold">
              {subject.full_name || subject.email.split("@")[0]}
            </p>
            <p className="text-foreground/55 truncate text-xs">{subject.email}</p>
          </div>
        </header>

        <div className="flex-1 scrollbar-thin overflow-y-auto px-6 py-5">
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

          <dl className="border-foreground/10 divide-foreground/10 mt-5 divide-y rounded-xl border">
            <KV label={t("userId")} value={subject.id} mono onCopy={handleCopyId} />
            <KV label={t("email")} value={subject.email} mono />
            {subject.full_name && <KV label={t("displayName")} value={subject.full_name} />}
            <KV label={t("joined")} value={formatDateTime(subject.created_at, locale)} />
          </dl>

          <section className="mt-7">
            <h3 className="text-foreground/55 mb-3 font-mono text-[11px] tracking-wider uppercase">
              {t("recentConversations")}
            </h3>
            {convsLoading ? (
              <LoadingState variant="skeleton-list" rows={3} />
            ) : convsError ? (
              // Not "No conversations." - a 502 and an account that has never
              // opened a chat are the same sentence, and an admin acting on the
              // second when it was the first is acting on nothing.
              <p className="text-destructive text-xs">
                {getErrorMessage(convsError, t("couldnTLoadConversations"))}
              </p>
            ) : !conversations || conversations.length === 0 ? (
              <p className="text-foreground/55 text-xs">{t("noConversationsFound")}</p>
            ) : (
              <ul className="space-y-1">
                {conversations.map((c) => (
                  <li
                    key={c.id}
                    className="border-foreground/10 bg-background flex items-center justify-between gap-2 rounded-lg border px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-foreground truncate text-xs font-medium">
                        {c.title || t("untitled")}
                      </p>
                      <p className="text-foreground/45 truncate font-mono text-[10px] tracking-wider uppercase">
                        {formatDateTime(c.created_at, locale)}
                        {typeof c.message_count === "number" &&
                          ` · ${t("messageCountShort", { count: c.message_count })}`}
                      </p>
                    </div>
                    <a
                      href={`${ROUTES.ADMIN_CONVERSATIONS}?id=${c.id}`}
                      className="text-foreground/55 hover:text-foreground inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors"
                      title={t("openConversation")}
                    >
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <footer className="border-foreground/10 flex flex-wrap items-center gap-2 border-t px-6 py-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onUpdate(subject.id, { is_active: !subject.is_active })}
            className="rounded-full"
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
            className="rounded-full"
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
          <Button variant="outline" size="sm" onClick={handleImpersonate} className="rounded-full">
            <KeyRound className="mr-1.5 h-3.5 w-3.5" />
            {t("impersonate")}
          </Button>

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive ml-auto rounded-full"
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
      <dt className="text-foreground/55 font-mono text-[10px] tracking-wider uppercase">{label}</dt>
      <dd className="flex items-center gap-2">
        <span className={mono ? "text-foreground font-mono text-xs" : "text-foreground text-xs"}>
          {value}
        </span>
        {onCopy && (
          <button
            type="button"
            onClick={onCopy}
            className="text-foreground/45 hover:text-foreground inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors"
            title={t("copy")}
          >
            <Copy className="h-3 w-3" />
          </button>
        )}
      </dd>
    </div>
  );
}
