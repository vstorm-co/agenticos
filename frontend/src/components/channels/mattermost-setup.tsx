"use client";

import { useId } from "react";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { CONTROL_FOCUS, SECONDARY_CONTROL } from "@/components/ui/control-styles";
import { cn } from "@/lib/utils";

export type MattermostSetup = "manual" | "plugin";

export const MATTERMOST_PLUGIN_URL = "https://github.com/vstorm-co/agenticos-mattermost";

export function MattermostSetupChoice({
  value,
  onChange,
}: {
  value: MattermostSetup;
  onChange: (value: MattermostSetup) => void;
}) {
  const t = useTranslations("pages.channels");
  const name = useId();
  return (
    <fieldset className="space-y-2" data-tour="channels-mattermost-setup">
      <legend className="text-sm font-medium">{t("mattermostSetupMethod")}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {(["manual", "plugin"] as const).map((option) => (
          <label
            key={option}
            htmlFor={`${name}-${option}`}
            className={cn(
              SECONDARY_CONTROL,
              "flex min-h-16 cursor-pointer items-start gap-3 rounded-xl border-2 p-3 transition-colors",
              value === option && "border-foreground/50 bg-control-active",
            )}
          >
            <input
              type="radio"
              id={`${name}-${option}`}
              name={name}
              value={option}
              checked={value === option}
              onChange={() => onChange(option)}
              className={cn(CONTROL_FOCUS, "accent-primary mt-0.5 size-4 shrink-0")}
            />
            <span className="space-y-1 text-sm font-medium">
              {t(option === "manual" ? "mattermostSetupManual" : "mattermostSetupPlugin")}
              <span className="text-muted-foreground block text-xs font-normal">
                {t(option === "manual" ? "mattermostSetupManualHint" : "mattermostSetupPluginHint")}
              </span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function MattermostPluginGuide({ organizationId }: { organizationId: string | null }) {
  const t = useTranslations("pages.channels");
  return (
    <section className="space-y-4 rounded-lg border p-4" aria-label={t("mattermostSetupPlugin")}>
      <p className="text-muted-foreground text-sm">{t("mattermostPluginIntro")}</p>
      <ol className="list-decimal space-y-3 pl-5 text-sm">
        <li>{t("mattermostPluginInstall")}</li>
        <li>{t("mattermostPluginConfigure")}</li>
        <li>{t.rich("mattermostPluginConnect", { command: (text) => <code>{text}</code> })}</li>
      </ol>
      {organizationId && (
        <p className="text-sm">
          {t.rich("mattermostPluginOrganization", {
            id: organizationId,
            code: (text) => <code className="break-all select-all">{text}</code>,
          })}
        </p>
      )}
      <a
        href={MATTERMOST_PLUGIN_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-10 items-center gap-2 text-sm underline underline-offset-4"
      >
        {t("mattermostPluginInstructions")}
        <ExternalLink className="size-3.5" aria-hidden />
      </a>
      <p className="text-muted-foreground text-xs">{t("mattermostPluginFinishHint")}</p>
    </section>
  );
}
