import { platformProxy } from "@/lib/platform-proxy";

// One preset by id. The proxy reads the whole path — the id segment included —
// from the request, so DELETE reaches the backend's per-preset route with the
// active organization header forwarded.
export const { GET, POST, PUT, PATCH, DELETE } = platformProxy();
