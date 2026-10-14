"use client";

import { useState } from "react";

import { useDatasets } from "@/hooks/use-datasets";
import { useAuthStore } from "@/stores/auth-store";
import type { Dataset } from "@/types/datasets";

const KEY = "agenticos:datasets:last";

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
  const { datasets, isLoading } = useDatasets({ sort: "updated", limit: 100, enabled });
  const editable = datasets.filter((dataset) => dataset.can_edit);
  const [chosen, setChosen] = useState<string | null>(null);
  const preferred = chosen ?? rememberedDataset(userId);
  const target: Dataset | undefined =
    editable.find((dataset) => dataset.id === preferred) ?? editable[0];
  return {
    editable,
    isLoading,
    target,
    choose: setChosen,
    remember: (dataset: Dataset) => rememberDataset(userId, dataset.id),
  };
}
