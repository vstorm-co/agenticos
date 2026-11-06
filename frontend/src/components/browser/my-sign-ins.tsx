"use client";

import { useState } from "react";
import { KeyRound, LogIn, LogOut } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { LinkFavicon } from "@/components/chat/link-favicon";
import { SectionCard } from "@/components/settings/settings-section";
import { useBrowserSignIns, useSignInToSite } from "@/hooks/use-browser-sign-ins";

import { SignInToSiteDialog } from "./sign-in-to-site-dialog";

/**
 * The sites your agents' browser starts signed in to, and forgetting one (#2129).
 *
 * A sign-in arrives here two ways, both of them you signing in yourself and
 * handing the browser back with "Keep me signed in" ticked: in a browse acting
 * as you that you took over, or in one you open here with "Sign in to a site".
 * Forgetting it means the next browse starts signed out there. What a sign-in
 * holds - cookies, storage - is never shown, and no route returns it.
 */
export function MySignIns() {
  const t = useTranslations("pages.signIns");
  const { available } = useSignInToSite();
  const [signingIn, setSigningIn] = useState(false);

  return (
    <SectionCard
      title={t("title")}
      description={t("description")}
      tour="my-sign-ins"
      action={
        available ? (
          <Button size="sm" onClick={() => setSigningIn(true)} data-tour="sign-in-to-site">
            <LogIn className="h-4 w-4" aria-hidden />
            {t("signInToSite")}
          </Button>
        ) : undefined
      }
    >
      <SignInList />
      {signingIn && <SignInToSiteDialog onClose={() => setSigningIn(false)} />}
    </SectionCard>
  );
}

function SignInList() {
  const t = useTranslations("pages.signIns");
  const format = useFormatter();
  const { signIns, isLoading, error, forget } = useBrowserSignIns();

  if (isLoading) return <LoadingState variant="skeleton-list" rows={2} />;
  if (error) return <ErrorState className="border-0 bg-transparent" />;
  if (signIns.length === 0) {
    return (
      <EmptyState
        className="border-0 bg-transparent"
        icon={KeyRound}
        title={t("empty")}
        description={t("emptyHint")}
      />
    );
  }

  const date = (stamp: string | null) =>
    stamp ? format.dateTime(new Date(stamp), { dateStyle: "medium" }) : null;

  return (
    <ul className="divide-foreground/[0.06] divide-y">
      {signIns.map((signIn) => {
        const used = date(signIn.last_used_at);
        return (
          <li
            key={signIn.id}
            className="flex items-center gap-3 py-4 first:pt-0 last:pb-0 sm:gap-4"
          >
            <span className="bg-background/60 ring-foreground/5 grid size-11 shrink-0 place-items-center rounded-xl ring-1">
              <LinkFavicon key={signIn.site} url={`https://${signIn.site}`} className="size-5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{signIn.site}</p>
              <p className="text-muted-foreground mt-1 text-xs leading-5">
                {used
                  ? t("savedAndUsed", { saved: date(signIn.created_at) ?? "", used })
                  : t("saved", { saved: date(signIn.created_at) ?? "" })}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => void forget(signIn.id)}>
              <LogOut className="size-3.5" aria-hidden />
              {t("forget")}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
