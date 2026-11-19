"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Command } from "cmdk";
import { Check, ChevronDown, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { useModelProviders, useProviderModels } from "@/hooks";
import { usableForAgents } from "@/lib/model-profiles";
import { ModelIcon } from "@/components/icons/model-icon";
import { Spinner } from "@/components/ui";
import { COMMAND_ITEM_FOCUS, CONTROL_FOCUS } from "@/components/ui/control-styles";
import { cn } from "@/lib/utils";

const VARIANTS = ["list", "library", "command"] as const;
type Variant = (typeof VARIANTS)[number];
export interface PreviewModel {
  id: string;
  model: string;
  name: string;
  provider: string;
  providerLabel?: string;
  maker: string;
  saved: boolean;
  context?: number | null;
}

/** Read-only design previews: choosing here never creates or changes a model profile. */
export function ModelPickerPreviewPage() {
  const t = useTranslations("chat.modelPreview");
  const params = useSearchParams();
  const variant = VARIANTS.find((entry) => entry === params.get("variant")) ?? "list";
  const { profiles, catalog: providers, isLoading, profilesStatus } = useModelProviders();
  const base = profiles.find(usableForAgents);
  const catalog = useProviderModels(base?.provider ?? "", base?.base_url ?? undefined);
  const models = useMemo(() => {
    const saved: PreviewModel[] = profiles.filter(usableForAgents).map((profile) => {
      const entry = catalog.models.find((item) => item.id === profile.model);
      return {
        id: profile.id,
        model: profile.model,
        provider: profile.provider,
        providerLabel: providers.find((item) => item.id === profile.provider)?.name,
        name:
          entry?.name.split(":").pop()?.trim() || profile.model.split("/").pop() || profile.model,
        maker: entry?.name.includes(":")
          ? entry.name.split(":")[0]!
          : profile.model.includes("/")
            ? profile.model.split("/")[0]!
            : profile.provider,
        context: profile.context_length,
        saved: true,
      };
    });
    const listed: PreviewModel[] = catalog.models
      .filter(
        (entry) =>
          !saved.some((item) => item.model === entry.id && item.provider === base?.provider),
      )
      .map((entry) => ({
        id: `catalog:${entry.id}`,
        model: entry.id,
        name: entry.name.split(":").pop()?.trim() || entry.id,
        provider: base?.provider ?? "",
        providerLabel: providers.find((item) => item.id === base?.provider)?.name,
        maker: entry.name.includes(":")
          ? entry.name.split(":")[0]!
          : entry.id.includes("/")
            ? entry.id.split("/")[0]!
            : (base?.provider ?? ""),
        saved: false,
        context: entry.context_length,
      }));
    return [...saved, ...listed];
  }, [profiles, providers, catalog.models, base?.provider]);
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="text-muted-foreground mt-2 max-w-2xl text-sm">{t("notice")}</p>
      <nav aria-label={t("variants")} className="mt-6 grid gap-3 sm:grid-cols-3">
        {VARIANTS.map((entry, index) => (
          <Link
            key={entry}
            href={`/dev/model-picker?variant=${entry}`}
            aria-current={variant === entry ? "page" : undefined}
            className={cn(
              CONTROL_FOCUS,
              "rounded-2xl border p-4 transition-colors",
              variant === entry
                ? "border-foreground/30 bg-muted/60"
                : "border-border hover:bg-muted/40",
            )}
          >
            <span className="block text-sm font-medium">
              {String.fromCharCode(65 + index)} · {t(entry)}
            </span>
            <span className="text-muted-foreground mt-1 block text-xs leading-relaxed">
              {t(`${entry}Description`)}
            </span>
          </Link>
        ))}
      </nav>
      <div className="bg-muted/25 mt-8 flex min-h-[620px] items-start justify-center rounded-3xl border p-4 pt-8 sm:p-8">
        {isLoading || (!models.length && catalog.isLoading) ? (
          <Spinner />
        ) : profilesStatus === "failed" ? (
          <p role="alert">{t("failed")}</p>
        ) : (
          <ModelPickerPreview key={variant} variant={variant} models={models} />
        )}
      </div>
    </div>
  );
}

export function ModelPickerPreview({
  variant,
  models,
}: {
  variant: Variant;
  models: readonly PreviewModel[];
}) {
  const t = useTranslations("chat.modelPreview");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [maker, setMaker] = useState<string | null>(null);
  const selected = models.find((entry) => entry.id === selectedId) ?? models[0];
  const makers = [...new Set(models.map((entry) => entry.maker))];
  const matches = models.filter(
    (entry) =>
      (!maker || maker === entry.maker) &&
      `${entry.name} ${entry.model} ${entry.provider}`.toLowerCase().includes(query.toLowerCase()),
  );
  const shown = matches.slice(0, 60);
  const dark = variant === "command";
  return (
    <section
      aria-label={t(variant)}
      className={cn(
        "w-full overflow-hidden rounded-2xl border shadow-[var(--shadow-float)]",
        variant === "library" ? "max-w-[640px]" : "max-w-[400px]",
        dark ? "border-white/15 bg-zinc-950 text-zinc-100" : "border-border bg-popover",
      )}
    >
      <Command shouldFilter={false} loop>
        <div
          className={cn(
            "flex items-center gap-2 px-4 py-3",
            dark ? "border-b border-white/10" : "border-border border-b",
          )}
        >
          <Search className="size-4 shrink-0 opacity-50" aria-hidden />
          <Command.Input
            aria-label={t("search")}
            placeholder={t("search")}
            value={query}
            onValueChange={setQuery}
            className="h-7 w-full min-w-0 bg-transparent text-sm outline-none placeholder:opacity-50"
          />
          {dark && (
            <kbd className="rounded border border-white/20 px-1.5 py-0.5 text-[10px]">↵</kbd>
          )}
        </div>
        {variant === "list" && selected && (
          <div className="border-border mx-2 border-b px-2 py-3">
            <span className="text-muted-foreground mb-2 block text-[11px]">{t("current")}</span>
            <div className="flex items-center gap-2.5">
              <ModelIcon model={selected.model} provider={selected.provider} />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{selected.name}</span>
              <Check className="size-3.5" aria-hidden />
            </div>
          </div>
        )}
        <div
          className={cn(
            variant === "library" &&
              "grid grid-cols-[120px_minmax(0,1fr)] sm:grid-cols-[160px_minmax(0,1fr)]",
          )}
        >
          {variant === "library" && (
            <div
              role="group"
              aria-label={t("makers")}
              className="border-border bg-muted/25 max-h-[360px] space-y-1 overflow-y-auto border-r p-2"
            >
              {[null, ...makers].map((entry) => (
                <button
                  key={entry ?? "all"}
                  type="button"
                  aria-pressed={maker === entry}
                  onClick={() => setMaker(entry)}
                  className={cn(
                    CONTROL_FOCUS,
                    "flex w-full min-w-0 items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs",
                    maker === entry
                      ? "bg-control-active font-medium"
                      : "text-muted-foreground hover:bg-muted/60",
                  )}
                >
                  <span className="truncate">{entry ?? t("all")}</span>
                </button>
              ))}
            </div>
          )}
          <Command.List className="max-h-[360px] min-h-28 scrollbar-thin overflow-y-auto p-2">
            <Command.Empty className="px-4 py-8 text-center text-xs opacity-60">
              {t("empty")}
            </Command.Empty>
            {shown.map((entry) => (
              <Command.Item
                key={entry.id}
                value={entry.id}
                onSelect={() => setSelectedId(entry.id)}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-xl px-3 py-3 text-left",
                  dark ? "data-[selected=true]:bg-white/10" : COMMAND_ITEM_FOCUS,
                )}
              >
                <ModelIcon
                  model={entry.model}
                  provider={entry.provider}
                  className={variant === "library" ? "size-9" : undefined}
                />
                <span className="min-w-0 flex-1">
                  <span
                    className={cn(
                      "block truncate text-[13px] font-medium",
                      dark && "font-mono text-xs",
                    )}
                  >
                    {entry.name}
                  </span>
                  <span
                    className={cn(
                      "mt-0.5 block truncate text-[11px]",
                      dark ? "text-zinc-400" : "text-muted-foreground",
                    )}
                  >
                    {entry.providerLabel ?? entry.provider}
                    {entry.saved ? ` · ${t("saved")}` : ""}
                  </span>
                </span>
                {selected?.id === entry.id ? (
                  <Check className="size-3.5 shrink-0" aria-label={t("selected")} />
                ) : entry.context ? (
                  <span className="shrink-0 text-[10px] opacity-50">
                    {entry.context >= 1_000_000
                      ? `${Math.round(entry.context / 1_000_000)}M`
                      : `${Math.round(entry.context / 1000)}K`}
                  </span>
                ) : null}
              </Command.Item>
            ))}
          </Command.List>
        </div>
      </Command>
      <div
        className={cn(
          "flex items-center justify-between gap-3 border-t px-4 py-3",
          dark ? "border-white/10 text-zinc-400" : "border-border text-muted-foreground",
        )}
      >
        <span className="text-[11px]">{t("preview")}</span>
        {selected && (
          <span className="flex min-w-0 items-center gap-1 text-xs">
            <span className="truncate">{selected.name}</span>
            <ChevronDown className="size-3 shrink-0" aria-hidden />
          </span>
        )}
      </div>
    </section>
  );
}
