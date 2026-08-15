import { platformProxy } from "@/lib/platform-proxy";

// Org-scoped like the layout it sits under - a preset is per user *and* per
// org - so it forwards the active organization header rather than resolving
// against the caller's personal org. The proxy takes the path from the
// request, so this reaches the backend's presets collection unchanged.
export const { GET, POST, PUT, PATCH, DELETE } = platformProxy();
