"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createPreset,
  deletePreset,
  listPresets,
  type DashboardPreset,
} from "@/lib/dashboard-preset-api";
import type { StoredEntry } from "@/lib/dashboard/preference";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

interface UseDashboardPresetsResult {
  presets: DashboardPreset[];
  isLoading: boolean;
  savePreset: (name: string, entries: StoredEntry[]) => Promise<DashboardPreset>;
  removePreset: (presetId: string) => Promise<void>;
}

/**
 * The caller's named dashboard presets for the active organization.
 *
 * Keyed on the organization so switching org refetches rather than offering
 * one org's presets on another's dashboard. Both mutations invalidate the list
 * rather than writing the cache by hand: a create is refused server-side on a
 * duplicate name or at the per-person cap, so the authoritative list is the one
 * the server returns, not one this layer guesses at.
 */
export function useDashboardPresets(): UseDashboardPresetsResult {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const queryKey = qk.dashboard.presets(activeOrgId ?? "current");

  const { data, isLoading } = useQuery({ queryKey, queryFn: listPresets });

  const invalidate = () => queryClient.invalidateQueries({ queryKey });

  const createMutation = useMutation({
    mutationFn: ({ name, entries }: { name: string; entries: StoredEntry[] }) =>
      createPreset(name, entries),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: (presetId: string) => deletePreset(presetId),
    onSuccess: invalidate,
  });

  const savePreset = useCallback(
    (name: string, entries: StoredEntry[]) => createMutation.mutateAsync({ name, entries }),
    [createMutation],
  );

  const removePreset = useCallback(
    async (presetId: string) => {
      await deleteMutation.mutateAsync(presetId);
    },
    [deleteMutation],
  );

  return {
    presets: data ?? [],
    isLoading,
    savePreset,
    removePreset,
  };
}
