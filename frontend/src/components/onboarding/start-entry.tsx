"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@/lib/locale-navigation";
import { useOrganizationList } from "@/hooks/use-organizations";
import { useStart } from "@/hooks/use-start";
import { shouldOfferStart } from "@/lib/onboarding-api";
import { setUrlParam } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";
import { StartSkeleton, startLoadingView } from "./start-skeleton";
import { useStartVariant } from "./start-experience";
import { StartHub } from "./start-hub";
import { StartPreferences } from "./start-preferences";
import { AcceptStagedInvitation } from "@/components/orgs/accept-staged-invitation";
import { ReceivedInvitations } from "@/components/orgs/received-invitations";

/** Automatic welcome links must not interrupt an already usable workspace. */
export function StartEntry() {
  const search = useSearchParams();
  const variant = useStartVariant();
  const appAdmin = useAuthStore((state) => state.user?.is_app_admin === true);
  const automatic = search.get("welcome") === "1";
  const freshEntry = search.get("entry") === "account" || search.get("entry") === "joined";
  const resuming = search.has("start-step");
  const [preferencesFinished, setPreferencesFinished] = useState(false);
  const showPreferences =
    freshEntry && !resuming && !preferencesFinished && search.get("preferences") !== "done";
  const userId = useAuthStore((state) => state.user?.id);
  const state = useStart();
  const scope = state.data?.organization_id;
  const completed = state.data?.completed;
  const query = search.toString();
  useEffect(() => {
    if (!userId || !scope || state.error || state.isLoading) return;
    const navigation = useOnboardingLocationStore.getState();
    if (completed) navigation.clearStartLocation(userId, scope);
    else {
      const search = new URLSearchParams(query);
      const location = new URLSearchParams();
      for (const key of ["start-step", "workspace", "question", "variant"]) {
        const value = search.get(key);
        if (value !== null) location.set(key, value);
      }
      navigation.rememberStartLocation(userId, scope, `/onboarding?${location}`);
    }
  }, [userId, scope, completed, query, state.error, state.isLoading]);
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
    automatic &&
    !resuming &&
    !freshEntry &&
    !memberWelcome &&
    !!state.data &&
    !shouldOfferStart(state.data);
  useEffect(() => {
    if (established) router.replace("/chat");
  }, [established, router]);
  const waitingForScope =
    state.isLoading || (state.waitingForScope && !!organizations.data?.length);
  const invitation = search.has("flow") ? (
    <AcceptStagedInvitation presentation="inline" />
  ) : (
    <ReceivedInvitations presentation="inline" />
  );
  if (showPreferences)
    return (
      <StartPreferences
        onContinue={() => {
          setUrlParam("preferences", "done");
          setPreferencesFinished(true);
        }}
      >
        {invitation}
      </StartPreferences>
    );
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
        workspaceCount={organizations.data?.length}
        steps={
          (appAdmin ? 9 : search.get("start-step")?.startsWith("admin.") ? 8 : 5) +
          (variant ? 2 : 0)
        }
      />
    );
  return <StartHub />;
}
