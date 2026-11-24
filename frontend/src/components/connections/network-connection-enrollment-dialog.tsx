"use client";

import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import type { NetworkConnection, NetworkEnrollment } from "@/types/network-connections";

function safeLoginUrl(value: string | null): string | null {
  if (
    !value ||
    value.length > 4096 ||
    /[\s\u0000-\u001f\u007f-\u009f]/u.test(value) ||
    value.includes("#")
  ) {
    return null;
  }
  try {
    const parsed = new URL(value);
    const authority = value.match(/^https:\/\/([^/?#]*)/i)?.[1];
    if (
      parsed.protocol !== "https:" ||
      parsed.hostname !== "login.tailscale.com" ||
      parsed.port !== "" ||
      parsed.username !== "" ||
      parsed.password !== "" ||
      parsed.hash !== "" ||
      !authority ||
      authority.includes("@") ||
      !parsed.pathname.startsWith("/a/")
    ) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

export function NetworkConnectionEnrollmentDialog({
  open,
  onOpenChange,
  connection,
  enrollment,
  currentState,
  stateLoading,
  stateError,
  canManage,
  available,
  refreshing,
  onRefreshStatus,
  onRestart,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connection: NetworkConnection;
  enrollment: NetworkEnrollment;
  currentState?: NetworkConnection;
  stateLoading: boolean;
  stateError: boolean;
  canManage: boolean;
  available: boolean | null;
  refreshing: boolean;
  onRefreshStatus: () => void;
  onRestart: () => void;
}) {
  const t = useTranslations("networkConnections");
  const state = currentState ?? connection;
  const loginUrl = safeLoginUrl(enrollment.login_url);
  const enrolled = state.auth_state === "authenticated";
  const enrolledIdle =
    enrolled && state.runtime_state === "stopped" && state.desired_state === "active";
  const canRefresh =
    canManage &&
    available === true &&
    state.desired_state === "active" &&
    enrolled &&
    state.runtime_state === "stopped";
  const canRestart = canManage && available === true && !enrolled;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t(enrolledIdle ? "enrollment.enrolledTitle" : "enrollment.title", {
              name: connection.name,
            })}
          </DialogTitle>
          <DialogDescription>{t("enrollment.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm" data-tour="tailscale-enrollment-status">
          {loginUrl && !enrolled && (
            <Button asChild>
              <a
                data-tour="tailscale-login"
                href={loginUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("enrollment.openLogin")}
              </a>
            </Button>
          )}
          {!loginUrl && !enrolled && (
            <p role="status" className="bg-muted text-muted-foreground rounded-lg p-3">
              {t(`status.auth.${state.auth_state}`)}
            </p>
          )}
          {state.auth_state === "sign_in_required" && <p>{t("enrollment.signIn")}</p>}
          {state.auth_state === "approval_required" && <p>{t("enrollment.approval")}</p>}
          {enrolled && state.runtime_state === "stopped" && (
            <p role="status" className="bg-muted rounded-lg p-3">
              {t("enrollment.enrolledIdle")}
            </p>
          )}
          {state.runtime_state === "starting" && <p role="status">{t("enrollment.starting")}</p>}
          {state.runtime_state === "running" && <p role="status">{t("enrollment.runtimeReady")}</p>}
          {state.runtime_state === "unavailable" && (
            <p role="status">{t("enrollment.runtimeUnavailable")}</p>
          )}
          {state.auth_state === "expired" && <p role="alert">{t("enrollment.expired")}</p>}
          {state.auth_state === "error" && <p role="alert">{t("enrollment.failed")}</p>}
          {stateError && <p role="alert">{t("enrollment.refreshFailed")}</p>}
          {stateLoading && <p className="text-muted-foreground">{t("enrollment.checking")}</p>}
          <p className="text-muted-foreground">{t("enrollment.adapterNotice")}</p>
          {enrollment.expires_at && (
            <p className="text-muted-foreground text-xs">
              {t("enrollment.expires", { time: new Date(enrollment.expires_at).toLocaleString() })}
            </p>
          )}
        </div>
        <DialogFooter>
          {canRefresh && (
            <Button variant="outline" onClick={onRefreshStatus} loading={refreshing}>
              {t("refreshStatus")}
            </Button>
          )}
          {canRestart && (
            <Button onClick={onRestart} disabled={refreshing}>
              {t("enrollment.restart")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
