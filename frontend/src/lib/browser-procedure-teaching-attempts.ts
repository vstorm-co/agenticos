import type { BrowserProcedureTeachingAudience } from "./browser-procedure-teaching-api";
import {
  isBrowserProcedureTeachingId,
  browserProcedureTeachingBudgetValid,
  browserProcedureTeachingOrigin,
} from "./browser-procedure-teaching-review";
import type {
  BrowserProcedureTeachingPropose,
  BrowserProcedureTeachingStart,
} from "@/types/browser-procedure-teaching";

export interface BrowserProcedureTeachingStartAttempt {
  kind: "start";
  body: BrowserProcedureTeachingStart;
  targetSkillId: string | null;
}
export interface BrowserProcedureTeachingDraftAttempt {
  kind: "propose";
  revision: number;
  body: BrowserProcedureTeachingPropose;
}
export type BrowserProcedureTeachingAttempt =
  BrowserProcedureTeachingStartAttempt | BrowserProcedureTeachingDraftAttempt;
export interface StoredBrowserProcedureTeachingAttempt<T extends BrowserProcedureTeachingAttempt> {
  attempt: T | null;
  blocked: boolean;
}
const PREFIX = "browser-procedure-teaching-attempt:";
const RETENTION_MS = 24 * 60 * 60 * 1_000;
const MAX_ATTEMPTS = 20;
const MAX_RECORD_LENGTH = 32_768;
export function browserProcedureTeachingAttemptKey(
  audience: BrowserProcedureTeachingAudience,
  kind: BrowserProcedureTeachingAttempt["kind"],
  identity: readonly string[],
): string {
  return PREFIX + JSON.stringify([audience.actor, audience.organization, kind, ...identity]);
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function keys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && actual.every((key) => expected.includes(key));
}
function isStart(value: Record<string, unknown>): boolean {
  const b = value.body;
  return (
    keys(value, ["kind", "body", "targetSkillId"]) &&
    record(b) &&
    keys(b, [
      "request_id",
      "run_id",
      "takeover_id",
      "call_id",
      "tab_id",
      "title",
      "allowed_origins",
    ]) &&
    typeof b.request_id === "string" &&
    isBrowserProcedureTeachingId(b.request_id) &&
    typeof b.run_id === "string" &&
    isBrowserProcedureTeachingId(b.run_id) &&
    typeof b.takeover_id === "string" &&
    isBrowserProcedureTeachingId(b.takeover_id) &&
    typeof b.call_id === "string" &&
    b.call_id.length > 0 &&
    b.call_id.length <= 200 &&
    typeof b.tab_id === "string" &&
    b.tab_id.length > 0 &&
    b.tab_id.length <= 200 &&
    typeof b.title === "string" &&
    b.title.trim().length > 0 &&
    b.title.length <= 160 &&
    Array.isArray(b.allowed_origins) &&
    b.allowed_origins.length > 0 &&
    b.allowed_origins.length <= 10 &&
    b.allowed_origins.every(
      (origin) =>
        typeof origin === "string" &&
        origin.length <= 2048 &&
        browserProcedureTeachingOrigin(origin) === origin,
    ) &&
    new Set(b.allowed_origins).size === b.allowed_origins.length &&
    (value.targetSkillId === null ||
      (typeof value.targetSkillId === "string" &&
        isBrowserProcedureTeachingId(value.targetSkillId)))
  );
}
function isAttempt(value: unknown): value is BrowserProcedureTeachingAttempt {
  if (!record(value)) return false;
  if (value.kind === "start") return isStart(value);
  if (
    value.kind !== "propose" ||
    !keys(value, ["kind", "revision", "body"]) ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) <= 0 ||
    !record(value.body)
  )
    return false;
  return value.body.mode === "reviewed"
    ? keys(value.body, ["mode"])
    : value.body.mode === "assistant" &&
        keys(value.body, ["mode", "max_cost_usd"]) &&
        typeof value.body.max_cost_usd === "string" &&
        browserProcedureTeachingBudgetValid(value.body.max_cost_usd);
}
function matchesKey(key: string, attempt: BrowserProcedureTeachingAttempt): boolean {
  if (!key.startsWith(PREFIX) || key.length > 2048) return false;
  const identity: unknown = JSON.parse(key.slice(PREFIX.length));
  if (
    !Array.isArray(identity) ||
    !identity.every((part) => typeof part === "string" && part.length > 0) ||
    identity[2] !== attempt.kind
  )
    return false;
  return attempt.kind === "start"
    ? identity.length === 6 &&
        identity[3] === attempt.body.run_id &&
        identity[4] === attempt.body.call_id &&
        identity[5] === attempt.body.tab_id
    : identity.length === 4 && isBrowserProcedureTeachingId(identity[3]);
}
function attemptIdentity(attempt: BrowserProcedureTeachingAttempt): string {
  if (attempt.kind === "propose") {
    return JSON.stringify([
      attempt.kind,
      attempt.revision,
      attempt.body.mode,
      attempt.body.mode === "assistant" ? attempt.body.max_cost_usd : null,
    ]);
  }
  const body = attempt.body;
  return JSON.stringify([
    attempt.kind,
    attempt.targetSkillId,
    body.request_id,
    body.run_id,
    body.call_id,
    body.tab_id,
    body.takeover_id,
    body.title,
    body.allowed_origins,
  ]);
}
/** Session storage preserves a lost acknowledgement across reload without storing site inputs. */
export function readBrowserProcedureTeachingAttempt<T extends BrowserProcedureTeachingAttempt>(
  key: string,
  kind: T["kind"],
  now = Date.now(),
): StoredBrowserProcedureTeachingAttempt<T> {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === null) return { attempt: null, blocked: false };
    if (raw.length > MAX_RECORD_LENGTH) return { attempt: null, blocked: true };
    const value: unknown = JSON.parse(raw);
    if (
      !record(value) ||
      !keys(value, ["createdAt", "attempt"]) ||
      !Number.isFinite(now) ||
      now < 0 ||
      typeof value.createdAt !== "number" ||
      !Number.isFinite(value.createdAt) ||
      value.createdAt < 0 ||
      value.createdAt > now ||
      now - value.createdAt >= RETENTION_MS ||
      !isAttempt(value.attempt) ||
      value.attempt.kind !== kind ||
      !matchesKey(key, value.attempt)
    ) {
      return { attempt: null, blocked: true };
    }
    return { attempt: value.attempt as T, blocked: false };
  } catch {
    return { attempt: null, blocked: true };
  }
}
export function retainBrowserProcedureTeachingAttempt(
  key: string,
  attempt: BrowserProcedureTeachingAttempt,
  now = Date.now(),
): boolean {
  try {
    if (!isAttempt(attempt) || !matchesKey(key, attempt) || !Number.isFinite(now) || now < 0)
      return false;
    const previous = readBrowserProcedureTeachingAttempt(key, attempt.kind, now);
    if (previous.blocked) return false;
    // An unresolved attempt cannot be replaced, and a retry must not renew retention.
    if (previous.attempt !== null)
      return attemptIdentity(previous.attempt) === attemptIdentity(attempt);
    let count = 0;
    for (let i = 0; i < sessionStorage.length; i++) {
      const existing = sessionStorage.key(i);
      if (existing?.startsWith(PREFIX)) count++;
    }
    if (count >= MAX_ATTEMPTS) return false;
    const raw = JSON.stringify({ createdAt: now, attempt });
    sessionStorage.setItem(key, raw);
    return sessionStorage.getItem(key) === raw;
  } catch {
    return false;
  }
}
/** Only a confirmed server outcome settles an uncertain attempt. */
export function clearBrowserProcedureTeachingAttempt(key: string): boolean {
  try {
    sessionStorage.removeItem(key);
    return sessionStorage.getItem(key) === null;
  } catch {
    return false;
  }
}
