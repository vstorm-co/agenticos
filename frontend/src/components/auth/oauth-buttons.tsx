"use client";

import { INVITATION_FLOW_PARAM, invitationFlowFrom } from "@/lib/invitation-links";
import { rememberReturnTo } from "@/lib/oauth-return";

import { KeyRound, Network, Ticket, type LucideIcon } from "lucide-react";

import { GlyphIcon } from "@/components/icons/glyph";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { AUTH_GLYPHS, type AuthProvider } from "@/lib/auth-glyphs.generated";
import type { PublicConfig, SignInProvider } from "@/lib/public-config";

import { useTranslations } from "next-intl";

type Variant = "signin" | "signup";

/**
 * Catalog keys, per provider and per variant.
 *
 * Written out rather than built from the provider name: "Continue with Google"
 * is a sentence somebody wrote, and a key assembled at runtime is a key the i18n
 * guard cannot see anybody reading.
 */
const PROVIDER_KEYS: Record<AuthProvider, Record<Variant, string>> = {
  google: { signin: "continueWithGoogle", signup: "signUpWithGoogle" },
  github: { signin: "continueWithGithub", signup: "signUpWithGithub" },
  microsoft: { signin: "continueWithMicrosoft", signup: "signUpWithMicrosoft" },
};

/** The generic providers', which take the name the deployment gave them. */
const GENERIC_KEYS: Record<Variant, string> = {
  signin: "continueWithProvider",
  signup: "signUpWithProvider",
};

type Unbranded = Exclude<SignInProvider, AuthProvider>;

/** Which configured name each unbranded provider goes by. */
const DISPLAY_NAME: Record<
  Unbranded,
  "oidcDisplayName" | "ldapDisplayName" | "kerberosDisplayName"
> = {
  oidc: "oidcDisplayName",
  ldap: "ldapDisplayName",
  kerberos: "kerberosDisplayName",
};

/**
 * A plain glyph for each unbranded provider. None of them is a brand, so none
 * gets a mark - bar the OIDC provider, whose deployment may pick one it ships.
 */
const PLAIN_ICON: Record<Unbranded, LucideIcon> = {
  oidc: KeyRound,
  ldap: Network,
  kerberos: Ticket,
};

function isBranded(provider: SignInProvider): provider is AuthProvider {
  return Object.hasOwn(PROVIDER_KEYS, provider);
}

function ProviderIcon({
  provider,
  oidcIcon,
}: {
  provider: SignInProvider;
  oidcIcon: AuthProvider | null;
}) {
  if (isBranded(provider)) {
    return <GlyphIcon glyph={AUTH_GLYPHS[provider]} className="h-4 w-4" aria-hidden />;
  }
  if (provider === "oidc" && oidcIcon) {
    return <GlyphIcon glyph={AUTH_GLYPHS[oidcIcon]} className="h-4 w-4" aria-hidden />;
  }
  const Plain = PLAIN_ICON[provider];
  return <Plain className="h-4 w-4" aria-hidden />;
}

/** The button's words: a branded provider's own sentence, or one around a configured name. */
function useProviderLabel(variant: Variant): (provider: SignInProvider) => string {
  const t = useTranslations("auth");
  const config: PublicConfig = usePublicConfig();
  return (provider) =>
    isBranded(provider)
      ? t(PROVIDER_KEYS[provider][variant])
      : t(GENERIC_KEYS[variant], { provider: config[DISPLAY_NAME[provider]] });
}

const BUTTON =
  "border-foreground/15 hover:border-foreground/40 hover:bg-foreground/[0.03] text-foreground inline-flex h-11 w-full items-center justify-center gap-3 rounded-full border px-5 text-sm font-medium transition-colors";

interface OAuthButtonsProps {
  providers: readonly SignInProvider[];
  variant: Variant;
  /**
   * Where the visitor was headed. Written to `sessionStorage` as the button is
   * clicked rather than sent to the provider: the trip starts and ends in this
   * tab, so nothing has to hold it for us (#135).
   */
  returnTo?: string | null;
  onDirectorySignIn?: () => void;
}

function OAuthButtons({ providers, variant, returnTo, onDirectorySignIn }: OAuthButtonsProps) {
  const { oidcIcon } = usePublicConfig();
  // A generic provider has no name of its own, so the deployment supplies one
  // and the label is built around it. The branded three keep their own catalog
  // entries: "Continue with Google" is a sentence somebody wrote, not a template
  // that happened to produce the same words.
  const labelFor = useProviderLabel(variant);
  // A same-origin start, so a staged invitation's httpOnly handle is attached
  // server-side before the cross-origin hop to the provider (#1414): the token is
  // never in this URL, only the flow naming which staging's cookie to attach, and
  // an `invite_only` link still admits its holder.
  const flow = invitationFlowFrom(returnTo);

  return (
    <div className="space-y-2.5">
      {providers.map((provider) => {
        const label = labelFor(provider);
        const icon = <ProviderIcon provider={provider} oidcIcon={oidcIcon} />;
        // A directory password is typed here rather than at a provider, so it is
        // not a redirect: the button turns the form into the directory's.
        if (provider === "ldap") {
          return (
            <button key={provider} type="button" onClick={onDirectorySignIn} className={BUTTON}>
              {icon}
              {label}
            </button>
          );
        }
        const url = flow
          ? `/api/oauth/${provider}/login?${INVITATION_FLOW_PARAM}=${flow}`
          : `/api/oauth/${provider}/login`;
        return (
          <a
            key={provider}
            href={url}
            // Also when there is nothing to remember: an abandoned deep link
            // left in storage would be resumed by the next sign-in from this tab.
            onClick={() => rememberReturnTo(returnTo)}
            className={BUTTON}
          >
            {icon}
            {label}
          </a>
        );
      })}
    </div>
  );
}

export function OAuthBlock({
  label,
  variant = "signin",
  returnTo,
  onDirectorySignIn,
}: {
  label: string;
  variant?: Variant;
  returnTo?: string | null;
  /**
   * Switches the sign-in form into its directory (LDAP) mode. Without it there
   * is no LDAP button: the register form passes none, because a directory
   * account is created on its first sign-in, from the sign-in page.
   */
  onDirectorySignIn?: () => void;
}) {
  const { oauthProviders } = usePublicConfig();
  const providers = oauthProviders.filter((provider) => provider !== "ldap" || onDirectorySignIn);
  if (providers.length === 0) return null;
  return (
    <div className="space-y-5">
      <OAuthDivider label={label} />
      <OAuthButtons
        providers={providers}
        variant={variant}
        returnTo={returnTo}
        onDirectorySignIn={onDirectorySignIn}
      />
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
