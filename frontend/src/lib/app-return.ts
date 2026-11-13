import { localePrefixOf } from "@/lib/locale-routing";

const BASE = "https://console.invalid";
const CONVERSATION = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Only a local conversation can be a model-written App link's return destination. */
export function appReturnTo(value: string | null | undefined): string | null {
  if (!value?.startsWith("/")) return null;
  let url: URL;
  try {
    url = new URL(value, BASE);
  } catch {
    return null;
  }
  const locale = localePrefixOf(url.pathname);
  const path = locale ? url.pathname.slice(locale.length + 1) : url.pathname;
  const id = url.searchParams.get("id");
  if (url.origin !== BASE || path !== "/chat" || !id || !CONVERSATION.test(id)) return null;
  return `${url.pathname}?id=${encodeURIComponent(id)}`;
}

/** Preserve where an App was opened, without accepting an arbitrary redirect. */
export function appLinkFromChat(path: string, current: string, origin = BASE): string {
  let target: URL;
  try {
    target = new URL(path, origin);
  } catch {
    return path;
  }
  const locale = localePrefixOf(target.pathname);
  const pathname = locale ? target.pathname.slice(locale.length + 1) : target.pathname;
  const back = appReturnTo(current);
  if (target.origin !== origin || !/^\/apps\/[^/]+$/.test(pathname) || back === null) return path;
  target.searchParams.set("returnTo", back);
  return `${target.pathname}${target.search}${target.hash}`;
}
