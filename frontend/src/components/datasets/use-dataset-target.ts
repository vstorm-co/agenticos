"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

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
 * Starts from the dataset the page's link named, or the one this person added
 * to last, so a second add is one click; falls back to the most recently
 * changed one they may edit. Remembered per browser and per person, and only
 * once an add succeeds.
 */
export function useDatasetTarget({ enabled = true }: { enabled?: boolean } = {}) {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  // A dataset's "Add from Activity" names it in the link, and it is picked first.
  const asked = useSearchParams().get("dataset");
  const [search, setSearch] = useState("");
  const query = useDebounced(search);
  const {
    datasets: editable,
    total,
    isLoading,
    create,
  } = useDatasets({ search: query, sort: "updated", limit: PICKER_SIZE, editable: true, enabled });
  const [chosen, setChosen] = useState<string | null>(null);
  const preferred = chosen ?? asked ?? rememberedDataset(userId);
  const target: Dataset | undefined =
    editable.find((dataset) => dataset.id === preferred) ?? editable[0];
  return {
    editable,
    isLoading,
    // Offered only once the listing stops short, so a short list stays a plain choice.
    search:
      total > editable.length || search !== "" ? { value: search, onChange: setSearch } : null,
    target,
    /** The dataset the link this page was opened from named, when it is the target. */
    returnTo: target !== undefined && target.id === asked ? target : undefined,
    choose: setChosen,
    remember: (dataset: Dataset) => rememberDataset(userId, dataset.id),
    create,
  };
}

/**
 * Whether to offer adding an answer to a dataset at all.
 *
 * The role's `datasets:edit` is enough, and so is an edit grant on any one
 * dataset, however old - a Viewer an owner shared a dataset with for editing may
 * add to it. When the role alone says no, the server is asked for one dataset the
 * caller may edit, so the answer never depends on which page a listing reached.
 */
export function useCanAddToDataset(): boolean {
  const { can } = usePermissions();
  const byRole = can(Perm.datasetsEdit);
  const { total } = useDatasets({ limit: 1, editable: true, enabled: !byRole });
  return byRole || total > 0;
}
