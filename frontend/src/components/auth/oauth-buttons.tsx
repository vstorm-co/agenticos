"use client";

import { BACKEND_URL } from "@/lib/constants";

import { BrandIcon } from "@/components/icons/brand-icon";

import { useTranslations } from "next-intl";
type Provider = "google" | "github" | "microsoft";

/** Catalog keys, per provider and per variant. */
const PROVIDER_WORDS: Record<Provider, string> = {
  google: "Google",
  github: "Github",
  microsoft: "Microsoft",
};

const ICON: Record<Provider, "google" | "github" | "microsoft"> = {
  google: "google",
  github: "github",
  microsoft: "microsoft",
};

function readProviders(): Provider[] {
  const raw = process.env.NEXT_PUBLIC_OAUTH_PROVIDERS;
  if (!raw) return [];
  return raw
    .split(",")
    .map((p) => p.trim().toLowerCase())
    .filter((p): p is Provider => p === "google" || p === "github" || p === "microsoft");
}

interface OAuthButtonsProps {
  next?: string;
  /** Override label suffix when used in register page. */
  variant?: "signin" | "signup";
  /**
   * The invitation this page was reached with, carried to the provider.
   *
   * On an `invite_only` deployment the token is what admits an address nothing else
   * recognises - a shareable link constraining neither an address nor a domain -
   * and without it the provider button refused exactly the people the link was
   * posted for, while the password form beside it accepted them. The backend takes
   * it off the query here and holds it in the session across the round trip.
   */
  invitation?: string | null;
}

function OAuthButtons({ next, variant = "signin", invitation }: OAuthButtonsProps) {
  const t = useTranslations("auth");
  const providers = readProviders();
  if (providers.length === 0) return null;

  const query = new URLSearchParams();
  if (next) query.set("next", next);
  if (invitation) query.set("invitation", invitation);
  const search = query.size > 0 ? `?${query.toString()}` : "";

  return (
    <div className="space-y-2.5">
      {providers.map((provider) => {
        const url = `${BACKEND_URL}/api/v1/oauth/${provider}/login${search}`;
        const label =
          variant === "signup"
            ? t(`signUpWith${PROVIDER_WORDS[provider]}`)
            : t(`continueWith${PROVIDER_WORDS[provider]}`);
        return (
          <a
            key={provider}
            href={url}
            className="border-foreground/15 hover:border-foreground/40 hover:bg-foreground/[0.03] text-foreground inline-flex h-11 w-full items-center justify-center gap-3 rounded-full border px-5 text-sm font-medium transition-colors"
          >
            <BrandIcon name={ICON[provider]} className="h-4 w-4" aria-hidden />
            {label}
          </a>
        );
      })}
    </div>
  );
}

export function OAuthBlock({
  label,
  variant,
  invitation,
}: {
  label: string;
  variant?: "signin" | "signup";
  invitation?: string | null;
}) {
  if (!process.env.NEXT_PUBLIC_OAUTH_PROVIDERS) return null;
  return (
    <div className="space-y-5">
      <OAuthDivider label={label} />
      <OAuthButtons variant={variant} invitation={invitation} />
    </div>
  );
}

function OAuthDivider({ label = "or" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="bg-foreground/15 h-px flex-1" />
      <span className="text-foreground/45 font-mono text-[11px] tracking-wider uppercase">
        {label}
      </span>
      <span className="bg-foreground/15 h-px flex-1" />
    </div>
  );
}
