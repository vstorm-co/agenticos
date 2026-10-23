import { NextResponse } from "next/server";

import { readPublicConfig } from "@/lib/public-config";

/**
 * Where this deployment's API and sockets answer, for the desktop app (#2305).
 *
 * The app is given a console's address, and the API is usually another origin.
 * To connect the computer as a device it needs both, and it asks the server it
 * was given rather than taking them from the console's page, where a script
 * could point the computer at another server. Public: the console sends both to
 * every visitor anyway.
 */
export function GET() {
  const { apiUrl, wsUrl } = readPublicConfig(process.env);
  return NextResponse.json(
    { api_url: apiUrl, ws_url: wsUrl },
    { headers: { "Cache-Control": "no-store" } },
  );
}
