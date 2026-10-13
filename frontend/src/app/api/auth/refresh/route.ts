import { NextRequest } from "next/server";
import { isImpersonation } from "@/lib/jwt-claims";
import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import { secureCookies } from "@/lib/session-cookie";
import type { RefreshTokenResponse } from "@/types";

export async function POST(request: NextRequest) {
  try {
    const refreshToken = request.cookies.get("refresh_token")?.value;

    if (!refreshToken) {
      return bffRefusal("NO_REFRESH_TOKEN", 401);
    }

    // An impersonation has no refresh token of its own; the one in the jar is
    // the administrator's. Minting from it here would answer a request the page
    // made as somebody else with the administrator's identity, and `apiClient`
    // would then replay that request as them (#1044). So a refused impersonation
    // is over, whichever way it ended: the cookie goes, the client is told, and
    // the administrator comes back deliberately through `/api/auth/me`.
    const accessToken = request.cookies.get("access_token")?.value;
    if (accessToken && isImpersonation(accessToken)) {
      const response = bffRefusal("IMPERSONATION_ENDED", 401);
      response.cookies.set("access_token", "", {
        httpOnly: true,
        secure: secureCookies(request),
        sameSite: "lax",
        maxAge: 0,
        path: "/",
      });
      return response;
    }

    const data = await backendFetch<RefreshTokenResponse>("/api/v1/auth/refresh", {
      method: "POST",
      headers: { ...forwardedFor(request) },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    const response = bffJson({
      access_token: data.access_token,
    });

    response.cookies.set("access_token", data.access_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 15, // 15 minutes
      path: "/",
    });

    // Rotate refresh token if backend returns a new one
    if (data.refresh_token) {
      response.cookies.set("refresh_token", data.refresh_token, {
        httpOnly: true,
        secure: secureCookies(request),
        sameSite: "lax",
        maxAge: 60 * 60 * 24 * 7, // 7 days
        path: "/",
      });
    }

    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      // A rate limit is a wait, not an expired session: forward it with its
      // Retry-After and leave the cookies alone, so exhausting the refresh
      // bucket does not sign the caller out (#1047).
      if (error.status === 429) return forwardRateLimit(error);
      // Only a refusal of the token ends the session. A 502 while the backend
      // redeploys says nothing about it - the rotation may even have gone
      // through with the answer lost, and the backend's reuse grace accepts the
      // cookie still held here, so clearing it is what would sign them out.
      if (error.status !== 401) return bffRefusal("INTERNAL_SERVER_ERROR", error.status);

      const response = bffRefusal("SESSION_EXPIRED", 401);

      response.cookies.set("access_token", "", {
        httpOnly: true,
        secure: secureCookies(request),
        sameSite: "lax",
        maxAge: 0,
        path: "/",
      });
      response.cookies.set("refresh_token", "", {
        httpOnly: true,
        secure: secureCookies(request),
        sameSite: "lax",
        maxAge: 0,
        path: "/",
      });

      return response;
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
