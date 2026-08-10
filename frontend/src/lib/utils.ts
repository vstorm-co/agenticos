import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function getErrorMessage(err: unknown, fallback = "An unexpected error occurred"): string {
  return err instanceof Error ? err.message : fallback;
}

export function isAppAdmin(user: { is_app_admin?: boolean } | null | undefined): boolean {
  // The one flag the backend gates /admin on. There used to be a
  // `role === "admin"` fallback here for template deployments that never set
  // it; the column is gone, and while it existed the fallback meant the client
  // showed an /admin surface that every request behind it was refused from.
  //
  // Optional rather than required: a persisted auth store can predate the flag,
  // and absent has to mean "not an admin" rather than `undefined === true`.
  return user?.is_app_admin === true;
}

export function setUrlParam(key: string, value: string | null): void {
  /* v8 ignore next -- an SSR guard, and the test environment is jsdom */
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (value === null) {
    url.searchParams.delete(key);
  } else {
    url.searchParams.set(key, value);
  }
  window.history.replaceState({}, "", url.toString());
}

export function getPasswordStrength(pw: string): { score: number; label: string; color: string } {
  if (!pw) return { score: 0, label: "", color: "" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^a-zA-Z0-9]/.test(pw)) score++;
  // Three tones, four scores: the number of filled segments already carries
  // the gradation, so colour only has to say bad / not yet / fine. The accent
  // is not one of them - password strength is a status, not an action.
  if (score <= 1) return { score: 1, label: "Weak", color: "bg-destructive" };
  if (score <= 2) return { score: 2, label: "Fair", color: "bg-warning" };
  if (score <= 3) return { score: 3, label: "Good", color: "bg-warning" };
  return { score: 4, label: "Strong", color: "bg-success" };
}

export const MAX_AVATAR_SIZE_BYTES = 2 * 1024 * 1024;

export const MAX_UPLOAD_SIZE_MB = parseInt(process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB || "50", 10);

export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return "0 B";
  const KB = 1024;
  const MB = KB * 1024;
  const GB = MB * 1024;
  if (bytes >= GB) return `${(bytes / GB).toFixed(2)} GB`;
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  if (bytes >= KB) return `${(bytes / KB).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function timeAgo(dateStr: string): string {
  const then = new Date(dateStr).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Math.round((Date.now() - then) / 1000);
  if (diff < 0) return "";
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatCurrency(
  amountCents: number,
  currency = "USD",
  minimumFractionDigits = 0,
): string {
  return (amountCents / 100).toLocaleString("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
    minimumFractionDigits,
  });
}

export function formatDate(date: Date | string | null | undefined): string {
  if (!date) return "-";
  const d = typeof date === "string" ? new Date(date) : date;
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * How long a run took, human-readable, or "-" when it has not finished.
 *
 * `ended_at` is nullable: a running or parked run has no duration yet, which is a
 * different fact from a run that was fast. The Took column and the duration sort
 * both rest on that distinction, so an unfinished run reads as unknown here and
 * never as zero.
 */
export function formatRunDuration(startedAt: string | null, endedAt: string | null): string {
  if (!startedAt || !endedAt) return "-";
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (Number.isNaN(ms) || ms < 0) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })} s`;
}

export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength - 3) + "...";
}
