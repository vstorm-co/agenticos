import { platformProxy } from "@/lib/platform-proxy";

// The person's own suggestions in the active organization (#2301): org-scoped, so
// through the shared forwarder that carries the organization header.
export const { GET, POST, PUT, PATCH, DELETE } = platformProxy();
