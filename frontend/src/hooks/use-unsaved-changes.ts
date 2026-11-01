"use client";

import { useCallback, useEffect, useRef } from "react";

import { removeCopy, writeCopy } from "@/lib/unsaved-copies";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";

interface UnsavedChangesOptions {
  /** Whether there is a change leaving would drop. */
  dirty: boolean;
  /** Saves it from here; true when saved. Absent where saving cannot happen from here. */
  save?: () => Promise<boolean>;
  /** Drops it. */
  discard: () => void;
  /**
   * Kept in this browser while there is a change, so leaving without deciding
   * loses nothing; forgotten once it is saved or discarded.
   */
  copy?: { key: string; base: number; value: unknown };
}

/**
 * Hold every way out of the page - and, for `leave`, out of this one place -
 * while `dirty`, asking first whether to save, discard or stay.
 *
 * Returns `forget`, for a save made from the place's own button: unmounting is
 * not deciding, so a copy outlives a component closed with a change still in it.
 */
export function useUnsavedChanges(
  id: string,
  { dirty, save, discard, copy }: UnsavedChangesOptions,
): { forget: () => void } {
  const latest = useRef({ save, discard, copy });
  useEffect(() => {
    latest.current = { save, discard, copy };
  });
  const key = copy?.key;
  const forget = useCallback(() => {
    if (key !== undefined) removeCopy(key);
  }, [key]);
  const canSave = save !== undefined;

  useEffect(() => {
    if (!dirty) return;
    const { register, unregister } = useUnsavedChangesStore.getState();
    register(id, {
      save: canSave
        ? async () => {
            const saved = (await latest.current.save?.()) ?? false;
            if (saved) forget();
            return saved;
          }
        : undefined,
      discard: () => {
        forget();
        latest.current.discard();
      },
    });
    return () => unregister(id);
  }, [id, dirty, canSave, forget]);

  const base = copy?.base;
  const kept = dirty && copy !== undefined ? JSON.stringify(copy.value) : null;
  useEffect(() => {
    if (key !== undefined && base !== undefined && kept !== null) {
      writeCopy(key, base, latest.current.copy?.value);
    }
  }, [key, base, kept]);

  // A change that went away while still here was saved or undone here.
  const was = useRef(dirty);
  useEffect(() => {
    if (was.current && !dirty) forget();
    was.current = dirty;
  }, [dirty, forget]);

  return { forget };
}
