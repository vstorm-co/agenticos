"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";

/** What one generated field is called, and what is said under it. */
export interface FieldCopy {
  title: string;
  description: string;
  options?: Record<string, { label: string; description: string; summary?: string }>;
}

/** The copy for a field of a generated form, or `null` to show the schema's own. */
export type FieldCopyFor = (field: string) => FieldCopy | null;

/**
 * A capability's settings, in the reader's language (#2098).
 *
 * The schema carries an English title and description for every field, and
 * `capabilityConfig.<capability>.<field>` holds the same two in each catalog -
 * `backend/tests/test_capability_registry.py` keeps the English one equal to
 * the schema. A field the catalog does not hold yet shows the schema's English
 * rather than its key.
 *
 * Read with `raw`: a prompt field's description names `{messages}` or
 * `{output}` for the person editing it, which ICU would take for an argument.
 */
export function useCapabilityFieldCopy(capabilityId: string): FieldCopyFor {
  const t = useTranslations("capabilityConfig");
  const choices = useTranslations("capabilityChoices");
  return useCallback(
    (field: string) => {
      if (!t.has(`${capabilityId}.${field}.title`)) return null;
      const title: unknown = t.raw(`${capabilityId}.${field}.title`);
      const description: unknown = t.raw(`${capabilityId}.${field}.description`);
      if (typeof title !== "string" || typeof description !== "string") return null;
      const path = `${capabilityId}.${field}`;
      if (!choices.has(path)) return { title, description };
      const raw: unknown = choices.raw(path);
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { title, description };
      const options: NonNullable<FieldCopy["options"]> = {};
      const entries: [string, unknown][] = Object.entries(raw);
      for (const [key, entry] of entries) {
        if (
          entry &&
          typeof entry === "object" &&
          "label" in entry &&
          "description" in entry &&
          typeof entry.label === "string" &&
          typeof entry.description === "string"
        ) {
          options[key] = {
            label: entry.label,
            description: entry.description,
            ...("summary" in entry && typeof entry.summary === "string"
              ? { summary: entry.summary }
              : {}),
          };
        }
      }
      return { title, description, options };
    },
    [t, choices, capabilityId],
  );
}
