import { revalidateTag } from "next/cache";
import type { NextRequest } from "next/server";

import { BRANDING_TAG } from "@/lib/branding-server";
import { platformProxy } from "@/lib/platform-proxy";

const proxy = platformProxy();

/**
 * A write that succeeded expires the cached branding read, so the name, the logo,
 * the sign-up policy or maintenance mode an administrator just saved is what the
 * next page renders - not what the data cache held before the save.
 */
function expiringBranding(
  handler: (request: NextRequest) => Promise<Response>,
): (request: NextRequest) => Promise<Response> {
  return async (request) => {
    const response = await handler(request);
    if (response.ok) {
      revalidateTag(BRANDING_TAG, { expire: 0 });
    }
    return response;
  };
}

export const GET = proxy.GET;
export const POST = expiringBranding(proxy.POST);
export const PUT = expiringBranding(proxy.PUT);
export const PATCH = expiringBranding(proxy.PATCH);
export const DELETE = expiringBranding(proxy.DELETE);
