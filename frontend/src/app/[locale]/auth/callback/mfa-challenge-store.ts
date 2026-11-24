"use client";

import type { MfaChallenge } from "@/hooks/use-auth";
import { takeReturnTo } from "@/lib/oauth-return";

export function createMfaChallengeStore() {
  let snapshot: MfaChallenge | null | undefined;
  return {
    subscribe: () => () => {},
    getSnapshot: (): MfaChallenge | null => {
      if (snapshot !== undefined) return snapshot;
      const mfaToken = new URLSearchParams(window.location.hash.slice(1)).get("mfa_token");
      if (mfaToken) {
        window.history.replaceState(
          window.history.state,
          "",
          window.location.pathname + window.location.search,
        );
        snapshot = {
          mfa_required: true,
          mfa_token: mfaToken,
          expires_in: 300,
          return_to: takeReturnTo(),
        };
      } else {
        snapshot = null;
      }
      return snapshot;
    },
    getServerSnapshot: () => null,
  };
}
