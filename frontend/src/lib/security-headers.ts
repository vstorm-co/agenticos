/**
 * The response headers every console page carries.
 *
 * Factored out of `next.config.ts` so each one can be asserted, the same reason
 * the [CSP](./csp.ts) is: a header that goes missing breaks nothing a build or a
 * log would notice, and the reason surfaces only as a refusal in one visitor's
 * browser (#1039, #1416).
 *
 * Two emitters, one list. The headers whose value never changes are set by
 * `next.config.ts` at build time. The Content-Security-Policy names the
 * deployment's public origins, which are read from the environment per request
 * (#1544), so `src/middleware.ts` stamps it on every page response - the one
 * place a runtime value can reach a header. Neither sets what the other does,
 * so no response carries a header twice.
 */

import { contentSecurityPolicy } from "./csp";
import type { PublicConfig } from "./public-config";

export interface SecurityHeader {
  key: string;
  value: string;
}

/** The headers whose value does not depend on the deployment, set by Next at build. */
export const staticSecurityHeaders: readonly SecurityHeader[] = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    // 0, not "1; mode=block": the legacy auditor is deprecated and its blocking
    // mode opens XS-Leak vectors, so OWASP is to disable it and rely on the CSP.
    // This matches the backend, so a response proxied through either carries one
    // value.
    key: "X-XSS-Protection",
    value: "0",
  },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    // Camera and geolocation are denied everywhere. The microphone is allowed on
    // this origin alone, because the chat's speech-to-text uses the Web Speech
    // API, which the `microphone` policy gates - denying it silently kills the
    // dictation button (#1416). A hosted page framed by a customer's site still
    // needs that site's `allow="microphone"` on the iframe on top of this.
    key: "Permissions-Policy",
    value: "camera=(), microphone=(self), geolocation=()",
  },
];

/** The policy header for a deployment, stamped per request by the middleware. */
export function contentSecurityPolicyHeader(config: PublicConfig): SecurityHeader {
  return { key: "Content-Security-Policy", value: contentSecurityPolicy(config) };
}
