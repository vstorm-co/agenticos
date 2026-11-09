"use client";
import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@/lib/locale-navigation";
import { useOrganizationList } from "@/hooks/use-organizations";
import { useStart } from "@/hooks/use-start";
import { shouldOfferStart } from "@/lib/onboarding-api";
import { useAuthStore } from "@/stores/auth-store";
import { StartSkeleton, startLoadingView } from "./start-skeleton";
import { StartHub } from "./start-hub";

/** Automatic welcome links must not interrupt an already usable workspace. */
export function StartEntry() {
  const search = useSearchParams();
  const appAdmin = useAuthStore((state) => state.user?.is_app_admin === true);
  const automatic = search.get("welcome") === "1";
  const freshEntry = search.get("entry") === "account" || search.get("entry") === "joined";
  const resuming = search.has("start-step");
  const state = useStart();
  const organizations = useOrganizationList();
  const router = useRouter();
  const memberWelcome =
    freshEntry &&
    !!state.data &&
    !state.data.completed &&
    !state.data.dismissed &&
    !state.data.has_activity &&
    !state.data.has_result;
  const established =
    automatic && !resuming && !memberWelcome && !!state.data && !shouldOfferStart(state.data);
  useEffect(() => {
    if (established) router.replace("/chat");
  }, [established, router]);
  const waitingForScope =
    state.isLoading || (state.waitingForScope && !!organizations.data?.length);
  if (established || organizations.isPending || ((automatic || resuming) && waitingForScope))
    return (
      <StartSkeleton
        view={
          search.has("start-step")
            ? startLoadingView(search.get("start-step"), search.get("question"))
            : appAdmin
              ? "workspace"
              : "welcome"
        }
        question={search.get("question")}
        workspaceCount={organizations.data?.filter((org) => !org.is_personal).length}
        steps={appAdmin ? 8 : search.get("start-step")?.startsWith("admin.") ? 7 : 4}
      />
    );
  return <StartHub />;
}
