import { NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

interface OAuthCallbackBody {
  access_token: string;
  refresh_token: string;
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as Partial<OAuthCallbackBody>;
    if (!body.access_token || !body.refresh_token) {
      return bffRefusal("MISSING_TOKENS", 400);
    }

    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${body.access_token}` },
    });

    const response = bffJson({
      user,
      access_token: body.access_token,
    });

    const isProd = process.env.NODE_ENV === "production";
    response.cookies.set("access_token", body.access_token, {
      httpOnly: true,
      secure: isProd,
      sameSite: "lax",
      maxAge: 60 * 15,
      path: "/",
    });
    response.cookies.set("refresh_token", body.refresh_token, {
      httpOnly: true,
      secure: isProd,
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7,
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = (error.data as { detail?: string })?.detail;
      if (!detail) return bffRefusal("LOGIN_FAILED", error.status);
      return bffJson({ detail }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
