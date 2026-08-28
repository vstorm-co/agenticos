import { type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  /** Where the link was minted to land. Signed into the token, so it cannot
      have been edited between the email and here; still judged again by
      `postSignInDestination` at the landing (#1214). */
  return_to?: string | null;
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const data = await backendFetch<TokenResponse>("/api/v1/auth/magic-link/verify", {
      method: "POST",
      body: JSON.stringify(body),
    });

    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });

    const response = bffJson({
      user,
      access_token: data.access_token,
      return_to: data.return_to ?? null,
    });

    const isProd = process.env.NODE_ENV === "production";
    response.cookies.set("access_token", data.access_token, {
      httpOnly: true,
      secure: isProd,
      sameSite: "lax",
      maxAge: 60 * 15,
      path: "/",
    });
    response.cookies.set("refresh_token", data.refresh_token, {
      httpOnly: true,
      secure: isProd,
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7,
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
