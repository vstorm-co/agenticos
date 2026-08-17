import { platformProxy } from "@/lib/platform-proxy";

// Org-scoped (the layout is per user *and* per org), so it forwards the active
// organization header rather than resolving against the caller's personal org -
// the reason it goes through the shared forwarder, not a hand-rolled route.
export const { GET, POST, PUT, PATCH, DELETE } = platformProxy();
