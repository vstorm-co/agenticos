import { platformProxy } from "@/lib/platform-proxy";

// The public API's own OpenAPI document, for the API reference page. Read-only,
// so only GET is mounted; the backend serves it without a session.
export const { GET } = platformProxy();
