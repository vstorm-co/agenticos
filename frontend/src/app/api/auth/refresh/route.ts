import { NextRequest } from "next/server";
import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import type { RefreshTokenResponse } from "@/types";

export async function POST(request: NextRequest) {
  try {
    const refreshToken = request.cookies.get("refresh_token")?.value;

    if (!refreshToken) {
      return bffRefusal("NO_REFRESH_TOKEN", 401);
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
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 15, // 15 minutes
      path: "/",
    });

    // Rotate refresh token if backend returns a new one
    if (data.refresh_token) {
      response.cookies.set("refresh_token", data.refresh_token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
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

      const response = bffRefusal("SESSION_EXPIRED", 401);

      response.cookies.set("access_token", "", {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        maxAge: 0,
        path: "/",
      });
      response.cookies.set("refresh_token", "", {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        maxAge: 0,
        path: "/",
      });

      return response;
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
