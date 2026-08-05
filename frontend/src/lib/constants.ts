export const APP_NAME = "agenticos";
export const APP_DESCRIPTION = "OS for your agents.";

export const API_ROUTES = {
  LOGIN: "/auth/login",
  REGISTER: "/auth/register",
  LOGOUT: "/auth/logout",
  REFRESH: "/auth/refresh",
  ME: "/auth/me",
  HEALTH: "/health",
  USERS: "/users",
  CHAT: "/chat",
} as const;

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
  RAG: "/rag",
  RAG_DETAIL: (id: string) => `/rag/${id}`,
  RAG_SEARCH: "/rag?tab=search",
  ADMIN: "/admin",
  ADMIN_USERS: "/admin/users",
  ADMIN_CONVERSATIONS: "/admin/conversations",
  ADMIN_RATINGS: "/admin/ratings",
  ADMIN_SYSTEM: "/admin/system",
  ORGS: "/orgs",
  ORGS_CREATE: "/orgs?create=1",
  ORG_MEMBERS: (id: string) => `/orgs/${id}/members`,
  ORG_ROLES: (id: string) => `/orgs/${id}/roles`,
  AGENTS: "/agents",
  AGENT_DETAIL: (id: string) => `/agents/${id}`,
  RUNS: "/runs",
  VAULT: "/vault",
  SKILLS: "/skills",
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
