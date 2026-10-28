"use client";
import { useAuth } from "./use-auth";
import { useAgents } from "./use-agents";
import { useAssistant } from "./use-assistant";
import { useDesktopState, useDeviceStatus, useDeviceLink } from "./use-desktop";
import { useDesktopReadiness } from "./use-desktop-readiness";
import { usePermissions } from "./use-permissions";
import { useTenantId } from "./use-organizations";
import { useAuthStore } from "@/stores";
import { desktopScope } from "@/stores/desktop-preferences-store";
import { SYSTEM_PERMISSIONS, type SystemPermission } from "@/lib/desktop/readiness";
import { Perm } from "@/types/permissions";

export type SetupState = "ready" | "missing" | "checking" | "error" | "unsupported";
export type SetupKey = SystemPermission | "account" | "device" | "agent" | "model" | "shortcuts";
export interface SetupItem {
  key: SetupKey;
  state: SetupState;
  href?: string;
}

/** Shared live facts for first connection, existing accounts and contextual repairs. */
export function useDesktopSetup() {
  const auth = useAuth();
  const userId = useAuthStore((s) => s.user?.id);
  const tenant = useTenantId();
  const scope = desktopScope(userId, tenant);
  const native = useDesktopReadiness();
  const device = useDeviceStatus();
  const link = useDeviceLink().link;
  const shell = useDesktopState();
  const agents = useAgents({ enabled: auth.isAuthenticated });
  const assistant = useAssistant({ enabled: auth.isAuthenticated });
  const { can } = usePermissions();
  const items: SetupItem[] = [
    {
      key: "account",
      state: auth.isLoading ? "checking" : auth.isAuthenticated ? "ready" : "missing",
      href: "/login",
    },
    {
      key: "device",
      state: device.error
        ? "error"
        : !device.data
          ? "checking"
          : device.data.linked && device.data.connected
            ? "ready"
            : "missing",
    },
    {
      key: "agent",
      state: !auth.isAuthenticated
        ? "checking"
        : agents.error
          ? "error"
          : agents.isLoading
            ? "checking"
            : agents.agents.some((a) => a.status === "published" && a.can_run)
              ? "ready"
              : "missing",
      href: "/agents",
    },
    {
      key: "model",
      state: !auth.isAuthenticated
        ? "checking"
        : assistant.error
          ? "error"
          : assistant.isLoading
            ? "checking"
            : assistant.assistant?.status === "needs_model"
              ? "missing"
              : assistant.assistant?.status === "ready"
                ? "ready"
                : "unsupported",
      href: assistant.assistant?.can_configure ? "/settings/assistant" : undefined,
    },
    ...SYSTEM_PERMISSIONS.map((key): SetupItem => ({
      key,
      state: native.status.error
        ? "error"
        : !native.status.data
          ? "checking"
          : native.status.data[key] === "granted"
            ? "ready"
            : native.status.data[key] === "unsupported"
              ? "unsupported"
              : "missing",
    })),
    {
      key: "shortcuts",
      state: shell.error
        ? "error"
        : !shell.data
          ? "checking"
          : shell.data.shortcuts.some((s) => s.problem) ||
              !shell.data.shortcuts.some((s) => s.action === "quick_ask" && s.accelerator)
            ? "missing"
            : "ready",
      href: "/settings/shortcuts",
    },
  ];
  return {
    items,
    scope,
    revision: native.status.data?.connection_revision,
    native,
    link,
    canManageAgents: can(Perm.agentsEdit),
    refresh: () => {
      void native.status.refetch();
      void device.refetch();
      void shell.refetch();
      if (auth.isAuthenticated) {
        void agents.refetch();
        assistant.retry();
      }
    },
  };
}
