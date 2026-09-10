"use client";

import { INVITATION_FLOW_PARAM, invitationFlowFrom } from "@/lib/invitation-links";
import { rememberReturnTo } from "@/lib/oauth-return";

import { GlyphIcon } from "@/components/icons/glyph";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { AUTH_GLYPHS, type AuthProvider } from "@/lib/auth-glyphs.generated";

import { useTranslations } from "next-intl";
type Provider = AuthProvider;

/** Catalog keys, per provider and per variant. */
const PROVIDER_WORDS: Record<Provider, string> = {
  google: "Google",
  github: "Github",
  microsoft: "Microsoft",
};

interface OAuthButtonsProps {
  /** Override label suffix when used in register page. */
  variant?: "signin" | "signup";
  /**
   * Where the visitor was headed. Written to `sessionStorage` as the button is
   * clicked rather than sent to the provider: the trip starts and ends in this
   * tab, so nothing has to hold it for us (#135).
   */
  returnTo?: string | null;
}

function OAuthButtons({ variant = "signin", returnTo }: OAuthButtonsProps) {
  const t = useTranslations("auth");
  const { oauthProviders: providers } = usePublicConfig();
  // A same-origin start, so a staged invitation's httpOnly handle is attached
  // server-side before the cross-origin hop to the provider (#1414): the token is
  // never in this URL, only the flow naming which staging's cookie to attach, and
  // an `invite_only` link still admits its holder.
  const flow = invitationFlowFrom(returnTo);

  return (
    <div className="space-y-2.5">
      {providers.map((provider) => {
        const url = flow
          ? `/api/oauth/${provider}/login?${INVITATION_FLOW_PARAM}=${flow}`
          : `/api/oauth/${provider}/login`;
        const label =
          variant === "signup"
            ? t(`signUpWith${PROVIDER_WORDS[provider]}`)
            : t(`continueWith${PROVIDER_WORDS[provider]}`);
        return (
          <a
            key={provider}
            href={url}
            // Also when there is nothing to remember: an abandoned deep link
            // left in storage would be resumed by the next sign-in from this tab.
            onClick={() => rememberReturnTo(returnTo)}
            className="border-foreground/15 hover:border-foreground/40 hover:bg-foreground/[0.03] text-foreground inline-flex h-11 w-full items-center justify-center gap-3 rounded-full border px-5 text-sm font-medium transition-colors"
          >
            <GlyphIcon glyph={AUTH_GLYPHS[provider]} className="h-4 w-4" aria-hidden />
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
  returnTo,
}: {
  label: string;
  variant?: "signin" | "signup";
  returnTo?: string | null;
}) {
  const { oauthProviders } = usePublicConfig();
  if (oauthProviders.length === 0) return null;
  return (
    <div className="space-y-5">
      <OAuthDivider label={label} />
      <OAuthButtons variant={variant} returnTo={returnTo} />
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
