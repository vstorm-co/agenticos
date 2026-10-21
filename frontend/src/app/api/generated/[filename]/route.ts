import { NextRequest, NextResponse } from "next/server";
import { bffRefusal } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ filename: string }> },
) {
  try {
    const { filename } = await params;
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) {
      return bffRefusal("NOT_AUTHENTICATED", 401);
    }

    // Forward ?download=true so an explicit Download control can force a save
    // dialog; the default renders the image inline in the chat.
    const qs = request.nextUrl.searchParams.toString();
    const url = `${BACKEND_URL}/api/v1/generated/${encodeURIComponent(filename)}${qs ? `?${qs}` : ""}`;
    // A player asks for byte ranges, and WebKit - Safari, and the desktop app -
    // plays an MP4 only from ranged answers, so the range travels both ways.
    const range = request.headers.get("range");
    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(range ? { Range: range } : {}),
      },
    });

    // A range past the end is not a missing file: the length it was refused
    // against goes back with it, as RFC 9110 asks, so the player can recover.
    if (response.status === 416) {
      return new NextResponse(null, {
        status: 416,
        headers: { "Content-Range": response.headers.get("content-range") ?? "" },
      });
    }
    if (!response.ok) {
      return bffRefusal("FILE_NOT_FOUND", response.status);
    }

    const data = await response.arrayBuffer();
    const contentType = response.headers.get("content-type") || "application/octet-stream";
    const disposition = response.headers.get("content-disposition") || "";

    const contentRange = response.headers.get("content-range");
    return new NextResponse(data, {
      status: response.status,
      headers: {
        "Accept-Ranges": "bytes",
        ...(contentRange ? { "Content-Range": contentRange } : {}),
        "Content-Type": contentType,
        "Content-Disposition": disposition,
        "Cache-Control": "private, max-age=3600",
        // Override the global X-Frame-Options: DENY from next.config.ts so the
        // chat can embed the image from the same origin.
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
      },
    });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
