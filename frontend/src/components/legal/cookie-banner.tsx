"use client";

import { useEffect, useState } from "react";
import { useAuthStore } from "@/stores";
import Link from "next/link";
import { Cookie, X } from "lucide-react";

import { ROUTES } from "@/lib/constants";
import { useTranslations } from "next-intl";

const STORAGE_KEY = "cookie.consent";

interface CookieConsent {
  essential: true;
  analytics: boolean;
  functional: boolean;
  decided_at: string;
}

function readConsent(): CookieConsent | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed.decided_at !== "string") return null;
    return parsed as CookieConsent;
  } catch {
    return null;
  }
}

function writeConsent(consent: CookieConsent) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(consent));
  window.dispatchEvent(new Event("cookie-consent-change"));
}

export function CookieBanner() {
  const t = useTranslations("legal");
  // Only for visitors who have not signed in. Inside the product it covered the
  // page to ask permission for something this deployment does not do - there is
  // no analytics script here, and nothing reads the stored consent. What a
  // signed-in employee's session may record is the operator's own policy, not a
  // question a browser prompt can settle.
  const { isAuthenticated } = useAuthStore();
  const [show, setShow] = useState(false);
  const [showPrefs, setShowPrefs] = useState(false);
  const [analytics, setAnalytics] = useState(true);
  const [functional, setFunctional] = useState(true);

  useEffect(() => {
    const decide = () => {
      const consent = readConsent();
      setShow(!consent && !isAuthenticated);
    };
    decide();
    window.addEventListener("storage", decide);
    window.addEventListener("cookie-consent-change", decide);
    return () => {
      window.removeEventListener("storage", decide);
      window.removeEventListener("cookie-consent-change", decide);
    };
  }, [isAuthenticated]);

  const close = () => setShow(false);

  const acceptAll = () => {
    writeConsent({
      essential: true,
      analytics: true,
      functional: true,
      decided_at: new Date().toISOString(),
    });
    close();
  };

  const rejectAll = () => {
    writeConsent({
      essential: true,
      analytics: false,
      functional: false,
      decided_at: new Date().toISOString(),
    });
    close();
  };

  const savePrefs = () => {
    writeConsent({
      essential: true,
      analytics,
      functional,
      decided_at: new Date().toISOString(),
    });
    close();
  };

  if (!show) return null;

  return (
    <div
      role="dialog"
      aria-labelledby="cookie-banner-title"
      className="fixed inset-x-0 bottom-0 z-[55] p-4 md:right-4 md:bottom-4 md:left-auto md:max-w-md"
    >
      <div className="border-foreground/15 bg-card text-foreground rounded-2xl border shadow-2xl">
        <div className="flex items-start gap-3 p-5">
          <span className="bg-brand/15 text-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full">
            <Cookie className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p
              id="cookie-banner-title"
              className="text-foreground text-sm font-semibold tracking-tight"
            >
              {t("weUseCookies")}
            </p>
            <p className="text-foreground/65 mt-1 text-xs leading-relaxed">
              {t.rich("cookieBannerBody", {
                policy: (chunks) => (
                  <Link
                    href={ROUTES.LEGAL_COOKIES}
                    className="text-foreground underline-offset-4 hover:underline"
                  >
                    {chunks}
                  </Link>
                ),
              })}
            </p>
          </div>
          <button
            type="button"
            aria-label={t("close")}
            onClick={close}
            className="text-foreground/45 hover:text-foreground hover:bg-foreground/5 -mt-1 -mr-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {showPrefs && (
          <div className="border-foreground/10 space-y-3 border-t px-5 py-4">
            <Toggle
              label={t("essential")}
              description={t("requiredKeepYouSigned")}
              checked
              disabled
              onChange={() => {}}
            />
            <Toggle
              label={t("analytics")}
              description={t("aggregatedAnonymizedUsageData")}
              checked={analytics}
              onChange={setAnalytics}
            />
            <Toggle
              label={t("functional")}
              description={t("remembersPreferencesThemeCookie")}
              checked={functional}
              onChange={setFunctional}
            />
          </div>
        )}

        <div className="border-foreground/10 flex flex-wrap items-center gap-2 border-t px-5 py-3">
          {showPrefs ? (
            <>
              <button
                type="button"
                onClick={savePrefs}
                className="bg-foreground text-background hover:bg-foreground/90 inline-flex items-center rounded-full px-4 py-1.5 text-xs font-medium transition-colors"
              >
                {t("savePreferences")}
              </button>
              <button
                type="button"
                onClick={() => setShowPrefs(false)}
                className="text-foreground/55 hover:text-foreground text-xs font-medium"
              >
                {t("back")}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={acceptAll}
                className="bg-foreground text-background hover:bg-foreground/90 inline-flex items-center rounded-full px-4 py-1.5 text-xs font-medium transition-colors"
              >
                {t("acceptAll")}
              </button>
              <button
                type="button"
                onClick={rejectAll}
                className="border-foreground/15 hover:border-foreground/40 text-foreground inline-flex items-center rounded-full border px-4 py-1.5 text-xs font-medium transition-colors"
              >
                {t("rejectOptional")}
              </button>
              <button
                type="button"
                onClick={() => setShowPrefs(true)}
                className="text-foreground/55 hover:text-foreground ml-auto text-xs font-medium"
              >
                {t("preferences")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Toggle({
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    // Label wraps a real (visually-hidden) <input type="checkbox"> plus its
    // descriptive text - an accessible pattern the static rule can't verify
    // through the nested span wrapper.
    // eslint-disable-next-line jsx-a11y/label-has-associated-control
    <label className="flex items-start justify-between gap-3">
      <span className="min-w-0 flex-1">
        <span className="text-foreground block text-xs font-semibold">{label}</span>
        <span className="text-foreground/55 mt-0.5 block text-[11px] leading-snug">
          {description}
        </span>
      </span>
      <span
        className={`relative inline-block h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-brand" : "bg-foreground/20"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only"
        />
        <span
          aria-hidden
          className={`bg-card absolute top-0.5 h-4 w-4 rounded-full shadow transition-transform ${
            checked ? "translate-x-[1.125rem]" : "translate-x-0.5"
          }`}
        />
      </span>
    </label>
  );
}
