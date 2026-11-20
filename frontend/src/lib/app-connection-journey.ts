import type {
  AppConnection,
  AppConnectionCallback,
  AppConnectionScope,
} from "@/types/app-connections";

export const APP_CONNECTION_GOALS = ["day", "inbox", "answers"] as const;
export type AppConnectionGoal = (typeof APP_CONNECTION_GOALS)[number];

export const GOAL_TOOLKITS: Record<AppConnectionGoal, readonly string[]> = {
  day: ["googlecalendar", "outlook"],
  inbox: ["gmail", "outlook"],
  answers: ["googledrive", "notion", "github", "slack"],
};

export function appConnectionGoalForToolkit(
  toolkit: string | null,
  preferred: AppConnectionGoal,
): AppConnectionGoal {
  if (!toolkit || GOAL_TOOLKITS[preferred].includes(toolkit)) return preferred;
  return APP_CONNECTION_GOALS.find((goal) => GOAL_TOOLKITS[goal].includes(toolkit)) ?? preferred;
}

export function appConnectionUsable(connection: AppConnection): boolean {
  return (
    connection.is_enabled &&
    connection.authorized &&
    connection.status === "connected" &&
    connection.readiness === "authorization_verified"
  );
}

export function appConnectionLabel(connection: AppConnection): string {
  const { identity, label, name } = connection;
  return identity && label && identity !== label
    ? `${label} · ${identity}`
    : identity || label || name;
}

export function appConnectionScopeKey(scope: AppConnectionScope): string {
  return JSON.stringify([scope.userId, scope.orgId]);
}

const CALLBACK_PARAMS = ["connection_attempt", "connected_account_id", "session_uri", "status"];

/** Query strings report an attempt, never a successful connection. */
export function readAppConnectionCallback(search: string): AppConnectionCallback | null {
  const params = new URLSearchParams(search);
  const attempt = params.get("connection_attempt");
  const session = params.get("session_uri");
  if (!attempt && !session) return null;
  const account = params.get("connected_account_id");
  return {
    ...(attempt ? { attempt_id: attempt } : {}),
    ...(session ? { session_uri: session } : {}),
    ...(account ? { connected_account_id: account } : {}),
  };
}

export function clearAppConnectionCallback(): void {
  const url = new URL(window.location.href);
  for (const param of CALLBACK_PARAMS) url.searchParams.delete(param);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

/** Only navigate to a validated HTTPS URL; the backend restricts its provider hosts. */
export function appAuthorizationUrl(raw: string): string | null {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

const STORAGE_PREFIX = "app-connection-goal:";

export function rememberAppConnectionGoal(
  scope: AppConnectionScope,
  goal: AppConnectionGoal,
): void {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + appConnectionScopeKey(scope), goal);
  } catch {
    // Browser storage can be disabled. The connection itself does not depend on it.
  }
}

export function rememberedAppConnectionGoal(scope: AppConnectionScope): AppConnectionGoal {
  try {
    const goal = sessionStorage.getItem(STORAGE_PREFIX + appConnectionScopeKey(scope));
    if (APP_CONNECTION_GOALS.includes(goal as AppConnectionGoal)) return goal as AppConnectionGoal;
  } catch {
    // A fresh journey is still usable when storage is disabled.
  }
  return "day";
}
