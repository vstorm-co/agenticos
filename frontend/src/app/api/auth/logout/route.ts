import { NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, forwardedFor } from "@/lib/server-api";

export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get("refresh_token")?.value;

  if (refreshToken) {
    try {
      await backendFetch("/api/v1/auth/logout", {
        method: "POST",
        headers: { ...forwardedFor(request) },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch (error) {
      // Ignore - we still want to clear the client cookies even if the
      // server-side invalidation fails (e.g. token already expired).
      if (!(error instanceof BackendApiError)) {
        // i18n-exempt: a log line for the server console, never rendered.
        console.error("Logout backend call failed:", error);
      }
    }
  }

  const response = bffJson({ ok: true });

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
