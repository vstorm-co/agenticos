import { NextRequest } from "next/server";
import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import type { LoginResponse } from "@/types";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Backend expects OAuth2 form data format
    const formData = new URLSearchParams();
    formData.append("username", body.email);
    formData.append("password", body.password);

    const data = await backendFetch<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        ...forwardedFor(request),
      },
      body: formData.toString(),
    });

    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });

    // Set HTTP-only cookies for tokens. Also return the access_token in the
    // body so the client can use it for cross-origin WebSocket auth.
    const response = bffJson({
      user,
      access_token: data.access_token,
    });

    response.cookies.set("access_token", data.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 15, // 15 minutes
      path: "/",
    });

    response.cookies.set("refresh_token", data.refresh_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7, // 7 days
      path: "/",
    });

    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      const detail = (error.data as { detail?: string })?.detail;
      if (!detail) return bffRefusal("LOGIN_FAILED", error.status);
      return bffJson({ detail }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
