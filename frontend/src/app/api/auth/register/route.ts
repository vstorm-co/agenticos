import { NextRequest } from "next/server";
import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import { INVITATION_FLOW_PARAM, isInvitationFlow, stageCookieName } from "@/lib/invitation-links";
import type { RegisterResponse } from "@/types";

/**
 * Create an account.
 *
 * The body is forwarded whole. When the registration arrives through a staged
 * invitation (#1414) the token is not in the body - it was exchanged for an
 * `httpOnly` handle before the invitee reached the form - so the handle rides that
 * cookie into a header here, where the backend peeks it for the sign-up admission
 * check. Peeked, not consumed: the same handle still closes the acceptance after
 * sign-in. Which cookie is the form's to say, through the `flow` it read off its
 * `returnTo`: two invitations staged side by side hold two cookies, and admitting
 * one address against the other's invitation would refuse the person it was for.
 *
 * A refusal is forwarded whole too, and that is the part worth saying. This used to
 * read `detail` off the backend's body and fall back to a generic
 * `REGISTRATION_FAILED` when there was none - and every refusal that matters here is
 * an `AppException`, which answers `{"error": {...}}` and carries no `detail`. So
 * "this deployment is invite-only", "that email domain cannot register" and "ask an
 * administrator for an account" all reached the form as "registration failed", which
 * tells somebody nothing about a rule they could satisfy. `getErrorMessage` reads the
 * envelope; passing it through is all that was needed.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const flow = request.nextUrl.searchParams.get(INVITATION_FLOW_PARAM);
    const stageHandle = isInvitationFlow(flow)
      ? request.cookies.get(stageCookieName(flow))?.value
      : undefined;

    const data = await backendFetch<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      headers: {
        ...forwardedFor(request),
        ...(stageHandle ? { "X-Invitation-Handle": stageHandle } : {}),
      },
      body: JSON.stringify(body),
    });

    return bffJson(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      return bffJson(error.data ?? { code: "REGISTRATION_FAILED" }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
