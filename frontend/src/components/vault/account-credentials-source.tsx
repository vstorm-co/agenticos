"use client";

import { useId } from "react";
import Image from "next/image";
import { Check, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { LOGO_DATA_URI } from "@/lib/logo.generated";
import { SECONDARY_CONTROL } from "@/components/ui/control-styles";
import { cn } from "@/lib/utils";

type Source = "own" | "agenticos";

export function AccountCredentialsSource({
  value,
  available,
  locked,
  onChange,
}: {
  value: Source;
  available: boolean;
  locked: boolean;
  onChange: (source: Source) => void;
}) {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  const id = useId();
  if (!available && value === "own") return null;
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-sm font-medium">{t("credentialsSource")}</legend>
      {(["agenticos", "own"] as const).map((source) => {
        const managed = source === "agenticos";
        const selected = value === source;
        const disabled = locked || (managed && !available);
        const title = t(managed ? "continueAgenticos" : "ownCredentials");
        return (
          <label key={source} htmlFor={`${id}-${source}`} className="relative block">
            <input
              id={`${id}-${source}`}
              type="radio"
              name={`${id}-source`}
              value={source}
              checked={selected}
              disabled={disabled}
              onChange={() => onChange(source)}
              className="peer sr-only"
            />
            <span
              className="pointer-events-none absolute start-3 top-3.5 flex size-8 items-center justify-center"
              aria-hidden
            >
              {managed ? (
                <Image src={LOGO_DATA_URI} width={32} height={32} alt="" unoptimized />
              ) : (
                <span className="bg-muted text-muted-foreground flex size-8 items-center justify-center rounded-lg">
                  <KeyRound className="size-4" />
                </span>
              )}
            </span>
            <span
              className={cn(
                "peer-focus-visible:outline-foreground/60 border-input bg-field block min-h-16 rounded-xl border-2 py-3 ps-14 pe-10 text-sm font-medium transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2",
                !disabled && cn(SECONDARY_CONTROL, "cursor-pointer"),
                selected && "border-foreground/50 bg-control-active",
                disabled && !selected && "text-muted-foreground",
              )}
            >
              {title}
              <span className="text-muted-foreground mt-0.5 block text-xs font-normal">
                {t(
                  managed ? (available ? "bridgeHelp" : "bridgeUnavailable") : "ownCredentialsHelp",
                )}
              </span>
            </span>
            {selected && (
              <span
                className="bg-foreground text-background pointer-events-none absolute end-3 top-4 flex size-4 items-center justify-center rounded-full"
                aria-hidden
              >
                <Check className="size-2.5" strokeWidth={3} />
              </span>
            )}
          </label>
        );
      })}
      {value === "agenticos" && available && (
        <p className="text-muted-foreground pt-1 text-xs leading-relaxed">{t("bridgePrivacy")}</p>
      )}
    </fieldset>
  );
}
