"use client";

import { useState, type ReactNode } from "react";
import { useUrlState } from "@/hooks/use-url-state";
import {
  Bell,
  Loader2,
  Palette,
  Save,
  Server,
  ShieldCheck,
  Smartphone,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { ServiceCard } from "@/components/settings/service-card";

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
  invalid?: boolean;
  onSave: () => void;
  onDiscard: () => void;
};

/** Keep drafts mounted across sections, including independently saved credentials. */
export function DeploymentSettingsLayout({
  dirty,
  pending,
  invalid = false,
  onSave,
  onDiscard,
  guided,
  onContinue,
  ...content
}: Props) {
  const t = useTranslations("pages.adminSettingsLayout");
  const tc = useTranslations("common");
  const tStart = useTranslations("start.administration");
  const [requestedSection, setSection] = useUrlState("section");
  const [guidedSection, setGuidedSection] = useState<Section>("access");
  const active = guided
    ? guidedSection
    : (SECTIONS.find((section) => section.id === requestedSection)?.id ?? "identity");

  return (
    <div className="space-y-4 pb-6">
      <div
        data-slot="deployment-settings-header"
        className={cn(
          "bg-background border-border sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b py-3",
          !guided && "top-[calc(-1*var(--page-inset-top,0px))] -mx-3 px-3 sm:-mx-6 sm:px-6",
        )}
      >
        <div className="min-w-0 flex-1 basis-full sm:basis-auto">
          <h2 className="text-base font-semibold tracking-tight">{t("title")}</h2>
          <p
            className="text-muted-foreground mt-1 text-xs leading-5 max-sm:sr-only"
            role="status"
            aria-live="polite"
          >
            {dirty ? t("unsaved") : t("hint")}
          </p>
        </div>
        <div className="ms-auto flex shrink-0 items-center gap-2">
          {dirty && (
            <Button variant="ghost" onClick={onDiscard} disabled={pending}>
              {t("discard")}
            </Button>
          )}
          <Button
            onClick={dirty ? onSave : onContinue}
            disabled={pending || invalid || (!dirty && !onContinue)}
          >
            {pending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
            {onContinue ? tStart("saveContinue") : tc("save")}
          </Button>
        </div>
      </div>
      <Tabs
        value={active}
        onValueChange={(value) => {
          const section = SECTIONS.find(({ id }) => id === value);
          if (section) {
            if (guided) setGuidedSection(section.id);
            else setSection(section.id);
          }
        }}
        className="min-w-0 space-y-4"
      >
        <TabsList aria-label={t("title")}>
          {SECTIONS.map(({ id, icon: Icon }) => (
            <TabsTrigger key={id} value={id} data-tour={`deployment-${id}-tab`} className="gap-2">
              <Icon className="size-4 shrink-0" aria-hidden />
              {t(id)}
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="min-w-0">
          {SECTIONS.map(({ id }) => (
            <TabsContent key={id} value={id} forceMount hidden={active !== id} className="mt-0">
              <p className="text-muted-foreground mb-4 max-w-2xl text-sm leading-6">
                {t(`${id}Hint`)}
              </p>
              <div
                className={cn(
                  "gap-4",
                  guided && (id === "access" || id === "identity")
                    ? "grid md:grid-cols-2 [&>*]:min-w-0"
                    : "space-y-4",
                )}
              >
                {content[id]}
              </div>
            </TabsContent>
          ))}
        </div>
      </Tabs>
    </div>
  );
}

export function DeploymentSettingsPanel({
  title,
  description,
  children,
  icon = Settings2,
}: {
  title: string;
  description: string;
  children: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <ServiceCard icon={icon} headingLevel={3} title={title} description={description} action={null}>
      {children}
    </ServiceCard>
  );
}
