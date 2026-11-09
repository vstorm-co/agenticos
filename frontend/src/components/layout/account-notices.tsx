"use client";

import { Suspense } from "react";
import { usePathname } from "next/navigation";
import { StartOffer } from "@/components/onboarding/start-offer";
import { ReceivedInvitations } from "@/components/orgs/received-invitations";
import { pageOf } from "@/lib/assistant-bubbles";
import { useAuthStore } from "@/stores/auth-store";
import styles from "./account-notices.module.css";

/** Account notices share an overlay so they cannot move or cover each other. */
export function AccountNotices() {
  const signedIn = useAuthStore((state) => state.isAuthenticated && !state.isLoading);
  const path = pageOf(usePathname());
  return (
    <div data-account-notices className={styles.stack}>
      <ReceivedInvitations />
      {signedIn && path === "/chat" && (
        <Suspense fallback={null}>
          <StartOffer />
        </Suspense>
      )}
    </div>
  );
}
