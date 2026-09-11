/**
 * The response headers every console page carries.
 *
 * Factored out of `next.config.ts` so each one can be asserted, the same reason
 * the [CSP](./csp.ts) is: a header that goes missing breaks nothing a build or a
 * log would notice, and the reason surfaces only as a refusal in one visitor's
 * browser (#1039, #1416).
 */

import { contentSecurityPolicy } from "./csp";

export interface SecurityHeader {
  key: string;
  value: string;
}

export const securityHeaders: readonly SecurityHeader[] = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    // 0, not "1; mode=block": the legacy auditor is deprecated and its blocking
    // mode opens XS-Leak vectors, so OWASP is to disable it and rely on the CSP.
    // This matches the backend and the bundled Nginx, so a proxied response does
    // not carry two conflicting values.
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
