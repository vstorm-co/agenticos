import { redirect } from "next/navigation";

import { ROUTES } from "@/lib/constants";

/**
 * The wizard's step URLs while it is being rebuilt.
 *
 * `/onboarding/welcome` and its siblings were live and are in people's history;
 * a 404 is a worse answer than the notice explaining where the flow went.
 */
export default function OnboardingStepRedirect() {
  redirect(ROUTES.ONBOARDING);
}
