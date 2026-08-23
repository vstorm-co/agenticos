export const APP_NAME = "agenticos";

export const ROUTES = {
  HOME: "/",
  LOGIN: "/login",
  REGISTER: "/register",
  FORGOT_PASSWORD: "/forgot-password",
  DASHBOARD: "/dashboard",
  CHAT: "/chat",
  PROFILE: "/profile",
  SETTINGS: "/settings",
  SETTINGS_PROFILE: "/settings/profile",
  SETTINGS_ACCOUNT: "/settings/account",
  SETTINGS_NOTIFICATIONS: "/settings/notifications",
  SETTINGS_SLASH_COMMANDS: "/settings/slash-commands",
  MCP_SERVERS: "/mcp-servers",
  CHANNELS: "/channels",
  RAG: "/rag",
  RAG_DETAIL: (id: string) => `/rag/${id}`,
  RAG_SEARCH: "/rag?tab=search",
  ADMIN: "/admin",
  ADMIN_USERS: "/admin/users",
  ADMIN_ORGANIZATIONS: "/admin/organizations",
  ADMIN_SYSTEM: "/admin/system",
  ADMIN_SETTINGS: "/admin/settings",
  ORGS: "/orgs",
  ORGS_CREATE: "/orgs?create=1",
  ORG_MEMBERS: (id: string) => `/orgs/${id}/members`,
  ORG_ROLES: (id: string) => `/orgs/${id}/roles`,
  AGENTS: "/agents",
  AGENT_DETAIL: (id: string) => `/agents/${id}`,
  RUNS: "/runs",
  ROUTINES: "/routines",
  VAULT: "/vault",
  SANDBOXES: "/sandboxes",
  WORKSPACES: "/workspaces",
  WORKSPACE_DETAIL: (id: string) => `/workspaces/${id}`,
  SKILLS: "/skills",
  CONTEXT: "/context",
  ORG_SETTINGS: (id: string) => `/orgs/${id}/settings`,
  BILLING: "/billing",
  BILLING_USAGE: "/billing/usage",
  BILLING_CREDITS: "/billing/credits",
  BILLING_INVOICES: "/billing/invoices",
  BILLING_PAYMENT_METHODS: "/billing/payment-methods",
  BILLING_SUBSCRIPTION: "/billing/subscription",
  ONBOARDING: "/onboarding",
  LEGAL_TERMS: "/legal/terms",
  LEGAL_PRIVACY: "/legal/privacy",
  LEGAL_COOKIES: "/legal/cookies",
} as const;

// WebSocket URL (for chat - direct to backend, use wss:// in production)
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

// Backend API URL (public, for direct links like API docs)
export const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// The published documentation. A self-hosted deployment can serve its own copy
// with `make docs`, but a panel cannot know whether one is running - so the
// links point at the canonical site.
export const DOCS_URL = "https://vstorm-co.github.io/agenticos";

/**
 * Documentation a control links to, anchored on the section that answers it.
 *
 * The top of a page is not an answer: somebody who followed a link from the
 * socket URL wants the frame table, and finding it themselves is the reading
 * this link exists to save.
 */
export const DOCS = {
  RAW_WEBSOCKET: `${DOCS_URL}/channels/#the-raw-websocket`,
  PUBLIC_API: `${DOCS_URL}/channels/#the-public-api`,
} as const;
