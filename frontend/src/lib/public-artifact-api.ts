/**
 * The one call a public artifact page makes from the browser: giving its password.
 *
 * Straight to the API rather than through a route handler of this origin, the way
 * the hosted chat uploads its files: a stranger has no session for a proxy to
 * carry, and the password is the whole request. The page's first load is fetched
 * server-side; only this second step needs the browser.
 */

import { ApiError, parseErrorMessage } from "@/lib/api-error";
import type { OpenPublicArtifact } from "@/types/artifact";

/**
 * The page behind a public link, opened with its password.
 *
 * @throws ApiError - 403 for a wrong password, 404 for a link that opens nothing,
 *   429 when the link's limit is spent.
 */
export async function unlockPublicArtifact(
  apiUrl: string,
  publicKey: string,
  password: string,
): Promise<OpenPublicArtifact> {
  const response = await fetch(
    `${apiUrl}/api/v1/public/artifacts/${encodeURIComponent(publicKey)}/unlock`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
      cache: "no-store",
    },
  );
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, parseErrorMessage(body), body);
  return body as OpenPublicArtifact;
}
