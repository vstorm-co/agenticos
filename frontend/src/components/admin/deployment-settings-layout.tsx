"use client";

import { useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import {
  Bell,
  ChevronRight,
  Loader2,
  Palette,
  Save,
  Server,
  ShieldCheck,
  Smartphone,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "identity", icon: Palette },
  { id: "access", icon: ShieldCheck },
  { id: "notices", icon: Bell },
  { id: "services", icon: Smartphone },
  { id: "operations", icon: Server },
] as const;

type Section = (typeof SECTIONS)[number]["id"];

type Props = Record<Section, ReactNode> & {
  guided?: boolean;
  onContinue?: () => void;
  dirty: boolean;
  pending: boolean;
  onSave: () => void;
  onDiscard: () => void;
};

/** Keep drafts mounted across sections, including independently saved credentials. */
export function DeploymentSettingsLayout({
  dirty,
  pending,
  onSave,
  onDiscard,
  guided,
  onContinue,
  ...content
}: Props) {
  const t = useTranslations("pages.adminSettingsLayout");
  const tc = useTranslations("common");
  const tStart = useTranslations("start.administration");
  const requestedSection = useSearchParams().get("section");
  const [active, setActive] = useState<Section>(
    guided
      ? "access"
      : (SECTIONS.find((section) => section.id === requestedSection)?.id ?? "identity"),
  );

  return (
    <div className="space-y-5 pb-6">
      <div className="bg-background/95 sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl py-3 backdrop-blur-md">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight">{t("title")}</h2>
          <p className="text-muted-foreground mt-1 text-sm" role="status" aria-live="polite">
            {dirty ? t("unsaved") : t("hint")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {dirty && (
            <Button variant="ghost" onClick={onDiscard} disabled={pending}>
              {t("discard")}
            </Button>
          )}
          <Button
            onClick={dirty ? onSave : onContinue}
            disabled={pending || (!dirty && !onContinue)}
          >
            {pending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
            {onContinue ? tStart("saveContinue") : tc("save")}
          </Button>
        </div>
      </div>
      <div
        className={cn("grid items-start gap-5", !guided && "lg:grid-cols-[190px_minmax(0,1fr)]")}
      >
        <nav
          aria-label={t("title")}
          className={cn(
            "bg-card flex gap-1 overflow-x-auto rounded-xl p-2",
            guided ? "flex-wrap" : "lg:sticky lg:top-24 lg:flex-col",
          )}
        >
          {SECTIONS.map(({ id, icon: Icon }) => (
            <button
              key={id}
              type="button"
              aria-current={active === id ? "page" : undefined}
              aria-controls={`deployment-${id}`}
              onClick={() => setActive(id)}
              className={cn(
                "focus-visible:ring-ring flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-3 text-left text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none",
                active === id
                  ? "bg-foreground/[0.09] text-foreground"
                  : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              {t(id)}
              <ChevronRight className="ml-auto hidden size-3.5 opacity-50 lg:block" aria-hidden />
            </button>
          ))}
        </nav>
        <div className="min-w-0">
          {SECTIONS.map(({ id }) => (
            <section key={id} id={`deployment-${id}`} aria-label={t(id)} hidden={active !== id}>
              <p className="text-muted-foreground mb-4 max-w-2xl text-sm leading-6">
                {t(`${id}Hint`)}
              </p>
              <div
                className={cn(
                  "gap-5",
                  guided && (id === "access" || id === "identity")
                    ? "grid md:grid-cols-2 [&>*]:min-w-0"
                    : "space-y-5",
                )}
              >
                {content[id]}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

export function DeploymentSettingsPanel({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-card shadow-card border-foreground/[0.06] overflow-hidden rounded-2xl border">
      <div className="border-foreground/[0.06] border-b px-5 py-4 sm:px-6">
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="text-muted-foreground mt-1 max-w-2xl text-xs leading-5">{description}</p>
      </div>
      <div className="p-5 sm:p-6">{children}</div>
    </div>
  );
}
