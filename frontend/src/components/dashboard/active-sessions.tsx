"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Globe, Monitor, Smartphone, Trash2 } from "lucide-react";
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
} from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { apiClient, ApiError } from "@/lib/api-client";
import { cn, getErrorMessage, timeAgo } from "@/lib/utils";
import type { Session, SessionListResponse } from "@/types";

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
 * the list — the row being revoked is on screen, and `total` comes back with
 * every fetch, so the component can tell that the page it is on has just
 * emptied and step back to the one before it rather than showing a blank card.
 */
export function ActiveSessions() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  // The backend may not expose sessions at all when the deployment was
  // generated without session management. Track that so the whole section is
  // hidden instead of showing a misleading "no data" placeholder.
  const [available, setAvailable] = useState(true);
  // A request that failed must not read as "you have no other devices". They
  // are opposite facts, and one of them is a reason to change your password.
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (which: number) => {
    setLoading(true);
    try {
      const data = await apiClient.get<SessionListResponse>("/sessions", {
        params: { skip: String(which * PAGE_SIZE), limit: String(PAGE_SIZE) },
      });
      setSessions(data.items);
      setTotal(data.total);
      setAvailable(true);
      setError(null);
    } catch (err) {
      // 404 = endpoint not exposed (session management disabled at gen time).
      if (err instanceof ApiError && err.status === 404) {
        setAvailable(false);
        return;
      }
      setError(getErrorMessage(err, "Couldn't load your sessions"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(page);
  }, [load, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  /** Reload after a revocation, stepping back when the page it emptied was the last one. */
  const reload = (remaining: number) => {
    const lastPage = Math.max(0, Math.ceil(remaining / PAGE_SIZE) - 1);
    if (page > lastPage) {
      setPage(lastPage);
      return;
    }
    load(page);
  };

  const handleRevoke = async (sessionId: string) => {
    try {
      await apiClient.delete(`/sessions/${sessionId}`);
      toast.success("Session revoked");
      reload(total - 1);
    } catch {
      toast.error("Failed to revoke session");
    }
  };

  const handleRevokeAll = async () => {
    try {
      await apiClient.delete("/sessions");
      toast.success("All other sessions revoked");
      reload(0);
    } catch {
      toast.error("Failed to revoke sessions");
    }
  };

  if (!available) return null;

  return (
    <SectionCard
      title="Active sessions"
      description="Devices currently signed in to your account."
      action={
        total > 0 ? (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm">
                Revoke all others
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Revoke all other sessions?</AlertDialogTitle>
                <AlertDialogDescription>
                  Every device signed in to your account will be signed out, except this one.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={handleRevokeAll}>Revoke all</AlertDialogAction>
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
        <p className="text-destructive text-sm">{error}</p>
      ) : sessions.length === 0 ? (
        <p className="text-muted-foreground text-sm">No session data available.</p>
      ) : (
        <>
          <ul className="space-y-2">
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
                      <span className="truncate">{session.device_name || "Unknown device"}</span>
                      {session.is_current && (
                        <span className="bg-card border-border text-muted-foreground inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase">
                          Current
                        </span>
                      )}
                    </p>
                    <p className="text-muted-foreground truncate text-xs">
                      {session.ip_address && `${session.ip_address} · `}
                      Last active {timeAgo(session.last_used_at)}
                    </p>
                  </div>
                </div>
                {!session.is_current && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-destructive h-8 shrink-0"
                    onClick={() => handleRevoke(session.id)}
                    title="Revoke session"
                    aria-label="Revoke session"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </li>
            ))}
          </ul>

          {totalPages > 1 && (
            <div className="mt-3 flex items-center justify-between">
              <span className="text-muted-foreground text-xs">
                {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0 || loading}
                  aria-label="Previous page"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-muted-foreground px-2 text-sm">
                  {page + 1} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1 || loading}
                  aria-label="Next page"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}
