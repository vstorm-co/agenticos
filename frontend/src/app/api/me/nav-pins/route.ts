import { platformProxy } from "@/lib/platform-proxy";

// Org-scoped (pins are per user and per org), so it forwards the active
// organization header through the shared forwarder.
export const { GET, POST, PUT, PATCH, DELETE } = platformProxy();
