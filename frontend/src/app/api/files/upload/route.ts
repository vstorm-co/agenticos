import { NextRequest, NextResponse } from "next/server";
import { bffRefusal } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) {
      return bffRefusal("NOT_AUTHENTICATED", 401);
    }

    const formData = await request.formData();

    const response = await fetch(`${BACKEND_URL}/api/v1/files/upload`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
      body: formData,
    });

    if (!response.ok) {
      const error: unknown = await response.json().catch(() => null);
      if (error === null) return bffRefusal("UPLOAD_FAILED", response.status);
      return NextResponse.json(error, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data, { status: 201 });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
