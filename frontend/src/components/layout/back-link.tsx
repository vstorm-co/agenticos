"use client";

import { useSyncExternalStore, type MouseEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { previousEntryInApp } from "@/lib/history-entries";

function subscribe(onChange: () => void): () => void {
  const navigation = (window as { navigation?: Navigation }).navigation;
  navigation?.addEventListener("currententrychange", onChange);
  return () => navigation?.removeEventListener("currententrychange", onChange);
}

/**
 * A page's own way back: the browser's Back when the page before it is one of
 * this app's, and the page's logical parent - `href`, with its tab - when there
 * is none, as after opening a link or a new tab.
 *
 * A link either way, so opening it in a new tab still opens the parent. It is
 * named for where it goes: plain "Back" for the step back, `label` for the parent.
 */
export function BackLink({
  href,
  label,
  className,
}: {
  href: string;
  label: string;
  className?: string;
}) {
  const t = useTranslations("common");
  const router = useRouter();
  const stepBack = useSyncExternalStore(subscribe, previousEntryInApp, () => false);
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
      return;
    }
    if (!previousEntryInApp()) return;
    event.preventDefault();
    router.back();
  };
  return (
    <Link href={href} onClick={onClick} className={className}>
      <ArrowLeft className="h-4 w-4" aria-hidden />
      {stepBack ? t("back") : label}
    </Link>
  );
}
