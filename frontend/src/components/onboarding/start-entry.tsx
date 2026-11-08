"use client";
import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@/lib/locale-navigation";
import { useOrganizationList } from "@/hooks/use-organizations";
import { useStart } from "@/hooks/use-start";
import { shouldOfferStart } from "@/lib/onboarding-api";
import { LoadingState } from "@/components/states";
import { StartHub } from "./start-hub";

/** Automatic welcome links must not interrupt an already usable workspace. */
export function StartEntry() {
  const automatic = useSearchParams().get("welcome") === "1";
  const state = useStart();
  const organizations = useOrganizationList();
  const router = useRouter();
  const established = automatic && !!state.data && !shouldOfferStart(state.data);
  useEffect(() => {
    if (established) router.replace("/chat");
  }, [established, router]);
  if (
    established ||
    (automatic &&
      (state.isLoading ||
        organizations.isPending ||
        (state.waitingForScope && !!organizations.data?.length)))
  )
    return <LoadingState variant="skeleton-panel" />;
  return <StartHub />;
}
