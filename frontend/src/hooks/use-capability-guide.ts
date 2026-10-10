"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";

/** One capability explained for somebody who has never built an agent. */
export interface CapabilityGuide {
  name: string;
  does: string;
  examples: string[];
  needs: string;
  never: string;
}

const EXAMPLE_SLOTS = [1, 2, 3] as const;

/**
 * Each capability in plain words, in the reader's language (#2070).
 *
 * The registry's `name` and `description` are one English sentence written for
 * whoever reads the API. This is the console's copy of it: what the capability lets
 * an agent do, two or three uses, what it needs and what it never does.
 * `backend/tests/test_capability_registry.py` holds the English names to the
 * registry's. `undefined` for a capability with no entry yet, which then shows the
 * registry's own words.
 */
export function useCapabilityGuide(): (capabilityId: string) => CapabilityGuide | undefined {
  const t = useTranslations("capabilityGuide");
  return useCallback(
    (id: string) => {
      if (!t.has(`${id}.does`)) return undefined;
      return {
        name: t(`${id}.name`),
        does: t(`${id}.does`),
        examples: EXAMPLE_SLOTS.filter((slot) => t.has(`${id}.example${slot}`)).map((slot) =>
          t(`${id}.example${slot}`),
        ),
        needs: t(`${id}.needs`),
        never: t(`${id}.never`),
      };
    },
    [t],
  );
}
