"use client";

import { useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Monitor, Smartphone, Trash2 } from "lucide-react";
import { toast } from "sonner";

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
  Button,
  PaginationBar,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { SectionCard } from "@/components/settings/settings-section";
import { apiClient, ApiError } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { cn, timeAgo } from "@/lib/utils";
import type { SessionListResponse } from "@/types";
import { useLocale, useTranslations } from "next-intl";

const PAGE_SIZE = 5;

function DeviceIcon({ type }: { type?: string | null }) {
  if (type === "mobile") return <Smartphone className="h-4 w-4" />;
  if (type === "desktop") return <Monitor className="h-4 w-4" />;
  return <Globe className="h-4 w-4" />;
}

/**
 * The devices signed in to this account, a page at a time.
 *
 * Paged because nothing bounds the list: every sign-in from every browser adds a
 * row that lives for the refresh token's lifetime, so a long-lived account
 * accumulates dozens and the settings page rendered all of them.
 *
 * The server holds the page, which is what makes revoking work from anywhere in
 * the list - the row being revoked is on screen, and `total` comes back with
 * every fetch, so the component can tell that the page it is on has just
 * emptied and step back to the one before it rather than showing a blank card.
 */
export function ActiveSessions() {
  const tErrors = useTranslations("errors");
  const t = useTranslations("dashboard");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [page, setPage] = useState(0);
  const queryClient = useQueryClient();

  // Through the query layer, which is where `.claude/rules/frontend.md` says
  // server data lives. It was five pieces of state and a `useCallback` fetch
  // driven by an effect; `useQuery` already has the list, the loading flag and
  // the refetch, and it does not write state synchronously from an effect.
  //
  // The one thing it does not have is the 404: a deployment generated without
  // session management does not expose this endpoint at all, and "hide the
  // section" is a different answer from "you have no other devices". That
  // stays an explicit shape rather than an error string somebody has to parse.
  const { data, isPending, isFetching, isPlaceholderData, error } = useQuery({
    queryKey: qk.sessions.list(page),
    queryFn: async (): Promise<SessionListResponse | "unavailable"> => {
      try {
        return await apiClient.get<SessionListResponse>("/sessions", {
          params: { skip: String(page * PAGE_SIZE), limit: String(PAGE_SIZE) },
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return "unavailable";
        throw err;
      }
    },
    // A page change is a new key. Without this the previous rows blank to
    // skeletons mid-navigation, the card collapses, and the scroll jumps (#944).
    placeholderData: keepPreviousData,
  });

  const available = data !== "unavailable";
  const sessions = data && data !== "unavailable" ? data.items : [];
  const total = data && data !== "unavailable" ? data.total : 0;
  const loading = isPending;

  /**
   * Reload after a revocation, stepping back when the page it emptied was the
   * last one.
   *
   * Every page is invalidated, not just the one on screen. A revocation shifts
   * the rows across all of them, and "revoke all others" from page two used to
   * step back to a page one that was still cached - listing, for the next five
   * minutes, the sessions it had just revoked.
   */
  const reload = (remaining: number) => {
    void queryClient.invalidateQueries({ queryKey: qk.sessions.all() });
    const lastPage = Math.max(0, Math.ceil(remaining / PAGE_SIZE) - 1);
    if (page > lastPage) setPage(lastPage);
  };

  const handleRevoke = async (sessionId: string) => {
    try {
      await apiClient.delete(`/sessions/${sessionId}`);
      toast.success(t("sessionRevoked"));
      reload(total - 1);
    } catch {
      toast.error(t("failedRevokeSession"));
    }
  };

  const handleRevokeAll = async () => {
    try {
      await apiClient.delete("/sessions");
      toast.success(t("allOtherSessionsRevoked"));
      reload(0);
    } catch {
      toast.error(t("failedRevokeSessions"));
    }
  };

  if (!available) return null;

  return (
    <SectionCard
      title={t("activeSessions")}
      description={t("devicesCurrentlySignedYour")}
      action={
        total > 0 ? (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm">
                {t("revokeAllOthers")}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t("revokeAllOtherSessions")}</AlertDialogTitle>
                <AlertDialogDescription>{t("everyDeviceSignedYour")}</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
                <AlertDialogAction onClick={handleRevokeAll}>{t("revokeAll")}</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : null
      }
    >
      {loading && sessions.length === 0 ? (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="bg-muted h-14 animate-pulse rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <p className="text-destructive text-sm">
          {getErrorMessage(error, tErrors, t("couldnTLoadYour"))}
        </p>
      ) : sessions.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noSessionDataAvailable")}</p>
      ) : (
        <>
          <ul
            aria-busy={isPlaceholderData || undefined}
            className={cn(
              "space-y-2 transition-opacity",
              isPlaceholderData && "pointer-events-none opacity-50",
            )}
          >
            {sessions.map((session) => (
              <li
                key={session.id}
                className={cn(
                  "border-border flex items-center justify-between gap-3 rounded-xl border px-4 py-3",
                  session.is_current ? "bg-muted" : "bg-card hover:bg-accent",
                )}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                    <DeviceIcon type={session.device_type} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground flex items-center gap-2 text-sm font-medium">
                      <span className="truncate">{session.device_name || t("unknownDevice")}</span>
                      {session.is_current && (
                        <span className="bg-card border-border text-muted-foreground inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase">
                          {t("current")}
                        </span>
                      )}
                    </p>
                    <p className="text-muted-foreground truncate text-xs">
                      {session.ip_address && `${session.ip_address} · `}
                      {t("lastActive", { when: timeAgo(session.last_used_at, tTime, locale) })}
                    </p>
                  </div>
                </div>
                {!session.is_current && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-destructive h-8 shrink-0"
                    onClick={() => handleRevoke(session.id)}
                    title={t("revokeSession")}
                    aria-label={t("revokeSession2")}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </li>
            ))}
          </ul>

          <div className="mt-3">
            <PaginationBar
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              isLoading={isFetching}
              onPage={setPage}
            />
          </div>
        </>
      )}
    </SectionCard>
  );
}
