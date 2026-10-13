"use client";

import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { ThinkingOrb } from "@/components/ui/thinking-orb";
import { useTranslations } from "next-intl";

/**
 * Sign in, sign up, and the password and magic-link pages around them.
 *
 * A white page with the form in a narrow column and, beside it on wide screens,
 * a soft grey panel holding the orb the chat shows while an agent works - the
 * one moving thing on the page, and the first glimpse of the product somebody
 * is signing in to. No badges, no licence line: the page asks for an email and
 * a password and gets out of the way.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("pages.auth");
  const { appName } = useBranding();

  return (
    <div className="theme-light bg-background text-foreground grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <main id="main" className="bg-card flex flex-col">
        <header className="flex h-16 items-center px-6 sm:px-10">
          {/* Not a link: the root redirects straight back here, so a brand mark
              that navigates would be a no-op. */}
          <span className="inline-flex items-center gap-2 text-base font-semibold tracking-tight">
            <BrandMark size={22} />
            {appName}
          </span>
        </header>
        <div className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </main>

      <aside aria-hidden className="hidden p-4 lg:block">
        <div className="bg-muted relative flex h-full flex-col items-center justify-center overflow-hidden rounded-3xl">
          <ThinkingOrb state="breathing" size={64} className="scale-[3.2]" />
          <p className="text-muted-foreground [&_b]:text-foreground mt-28 max-w-sm px-8 text-center text-lg leading-snug [&_b]:font-medium">
            {t.rich("tagline", { b: (chunks) => <b>{chunks}</b> })}
          </p>
        </div>
      </aside>
    </div>
  );
}
