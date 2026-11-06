"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getLocalState } from "@/lib/desktop/commands";

import { useDeviceStatus } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import {
  allowRoutine,
  chooseRoutineFolder,
  listRoutineGrants,
  revokeRoutineGrant,
} from "@/lib/desktop/routine-work";
import { isDesktopShell, reportShellFailure } from "@/lib/desktop/shell";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

export function useRoutineLocalWork() {
  const shell = useShell();
  const device = useDeviceStatus();
  const org = useOrgStore((state) => state.activeOrgId);
  const user = useAuthStore((state) => state.user?.id ?? null);
  const identity = device.data?.identity;
  const available = isDesktopShell(shell) && !!org && !!user && identity?.user_id === user;
  const queryClient = useQueryClient();
  const t = useTranslations("triggers.local");
  const key = qk.desktop.routineGrants(org, user, identity?.device_id ?? null);
  const localState = useQuery({
    queryKey: qk.desktop.local(),
    queryFn: getLocalState,
    enabled: available,
  });
  const supportsWrites = localState.data?.modes.includes("workspace_write") ?? false;
  const onError = (error: unknown) => {
    reportShellFailure("routine permission", error);
    toast.error(t("permissionFailed"));
  };
  const grants = useQuery({
    queryKey: key,
    queryFn: () => {
      // i18n-exempt: diagnostic only; the mutation renders permissionFailed from the catalog.
      if (!available || !org || !user) throw new Error("No paired routine owner");
      return listRoutineGrants(org, user);
    },
    enabled: available,
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: key });
  const pick = useMutation({ mutationFn: chooseRoutineFolder, onError });
  const allow = useMutation({ mutationFn: allowRoutine, onError, onSuccess: invalidate });
  const revoke = useMutation({
    mutationFn: (id: string) => {
      // i18n-exempt: diagnostic only; the mutation renders permissionFailed from the catalog.
      if (!available || !org || !user) throw new Error("No paired routine owner");
      return revokeRoutineGrant(id, org, user);
    },
    onError,
    onSuccess: invalidate,
  });
  return { available, identity, org, user, supportsWrites, grants, pick, allow, revoke };
}
