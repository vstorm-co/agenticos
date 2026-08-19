import { NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

/**
 * This deployment's name, mark and access policy - for anybody.
 *
 * The one route on this proxy with no session check, and it cannot have one: the
 * sign-in page, the register form and the maintenance screen all read it before a
 * session exists. It is `platformProxy`'s twin without the token, rather than a
 * path on the proxy itself, because that forwarder answers 401 without one.
 *
 * `bffJson` stamps `no-store`, which matters more here than elsewhere: a renamed
 * deployment that keeps answering its old name from a cache looks like a save
 * that did not take.
 */
export async function GET(_request: NextRequest) {
  try {
    const data = await backendFetch<unknown>("/api/v1/branding", { cache: "no-store" });
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
