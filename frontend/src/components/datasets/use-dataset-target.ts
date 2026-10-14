"use client";

import { useState } from "react";

import { useDebounced } from "@/components/ui/list-controls";
import { useDatasets } from "@/hooks/use-datasets";
import { usePermissions } from "@/hooks/use-permissions";
import { useAuthStore } from "@/stores/auth-store";
import type { Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";

const KEY = "agenticos:datasets:last";

/** The datasets a picker lists before it asks for a search. */
const PICKER_SIZE = 100;

function storageKey(userId: string | null): string {
  return `${KEY}:${userId ?? "anonymous"}`;
}

/** The dataset this person added to last, if this browser remembers one. */
export function rememberedDataset(userId: string | null): string | null {
  try {
    return localStorage.getItem(storageKey(userId));
  } catch {
    return null;
  }
}

export function rememberDataset(userId: string | null, datasetId: string): void {
  try {
    localStorage.setItem(storageKey(userId), datasetId);
  } catch {
    // A private window or blocked storage: the next add starts from the first dataset.
  }
}

/**
 * Which dataset an answer is about to go into, and the ones it could go into instead.
 *
 * Starts from the dataset this person added to last, so a second add is one
 * click; falls back to the most recently changed one they may edit. Remembered
 * per browser and per person, and only once an add succeeds.
 */
export function useDatasetTarget({ enabled = true }: { enabled?: boolean } = {}) {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const [search, setSearch] = useState("");
  const query = useDebounced(search);
  const { datasets, total, isLoading } = useDatasets({
    search: query,
    sort: "updated",
    limit: PICKER_SIZE,
    enabled,
  });
  const editable = datasets.filter((dataset) => dataset.can_edit);
  const [chosen, setChosen] = useState<string | null>(null);
  const preferred = chosen ?? rememberedDataset(userId);
  const target: Dataset | undefined =
    editable.find((dataset) => dataset.id === preferred) ?? editable[0];
  return {
    editable,
    isLoading,
    // Offered only once the listing stops short, so a short list stays a plain choice.
    search:
      total > datasets.length || search !== "" ? { value: search, onChange: setSearch } : null,
    target,
    choose: setChosen,
    remember: (dataset: Dataset) => rememberDataset(userId, dataset.id),
  };
}

/**
 * Whether to offer adding an answer to a dataset at all.
 *
 * The role's `datasets:edit` is enough, and so is an edit grant on one dataset -
 * a Viewer an owner shared a dataset with for editing may add to it, so the
 * listing's `can_edit` is asked when the role alone says no.
 */
export function useCanAddToDataset(): boolean {
  const { can } = usePermissions();
  const byRole = can(Perm.datasetsEdit);
  const { datasets } = useDatasets({ sort: "updated", limit: PICKER_SIZE, enabled: !byRole });
  return byRole || datasets.some((dataset) => dataset.can_edit);
}
