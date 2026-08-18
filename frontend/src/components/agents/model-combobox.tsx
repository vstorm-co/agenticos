"use client";

import { useId, useState } from "react";
import { Command } from "cmdk";
import { Check, ChevronsUpDown, Pencil } from "lucide-react";

import { Badge, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

/** One entry as the picker needs it - the shape `useProviderModels` returns. */
export interface ModelOption {
  id: string;
  name: string;
  context_length?: number | null;
}

interface ModelComboboxProps {
  value: string;
  onChange: (model: string) => void;
  options: ModelOption[];
  /** Where the list came from, so the panel can be honest about it. */
  source: "live" | "curated" | null;
  loading?: boolean;
  disabled?: boolean;
  placeholder: string;
  id?: string;
  /**
   * Injected by `FormField`, which is how every other control in this form is
   * marked. A combobox is a button rather than an input, so it carries them
   * itself instead of getting them from the primitive.
   */
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}

/** `1048576` is not a context window anybody reads. `1M` is. */
function contextLabel(tokens: number | null | undefined): string | null {
  if (typeof tokens !== "number" || tokens <= 0) return null;
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000;
    return `${millions % 1 === 0 ? millions : millions.toFixed(1)}M ctx`;
  }
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K ctx`;
  return `${tokens} ctx`;
}

/**
 * Which model to run on: the provider's catalog, searchable, still typeable.
 *
 * This was a text input with a `<datalist>` attached. The reasoning behind the
 * free-text field is sound and is kept - a provider ships a model the morning
 * after any catalog here was warmed, and a control that cannot express "that
 * one" is a control people work around by editing the spec by hand. What was
 * wrong is that a `datalist` is invisible: browsers render it as a hint that
 * appears once you have already typed a prefix, so a field backed by six hundred
 * known models looked exactly like a field backed by nothing, and the honest
 * conclusion from looking at it was that no list existed.
 *
 * So the list is a list. Search filters it, the panel says whether it came from
 * the provider or from this deployment's curated fallback, and anything typed
 * that matches nothing is offered as itself rather than refused - which is the
 * free-text case, now visible instead of implicit.
 */
export function ModelCombobox({
  value,
  onChange,
  options,
  source,
  loading,
  disabled,
  placeholder,
  id,
  "aria-invalid": invalid,
  "aria-describedby": describedBy,
}: ModelComboboxProps) {
  const t = useTranslations("agents");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const listId = useId();

  const chosen = options.find((option) => option.id === value);
  const typed = search.trim();
  // Only when it is genuinely not in the catalog. Offering "use openai/gpt-5"
  // beneath the openai/gpt-5 row is offering the same thing twice.
  const custom =
    typed !== "" && !options.some((option) => option.id.toLowerCase() === typed.toLowerCase())
      ? typed
      : null;

  const pick = (model: string) => {
    onChange(model);
    setSearch("");
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          disabled={disabled}
          className={cn(
            "border-input bg-background flex h-9 w-full items-center gap-2 rounded-md border px-3 text-left text-sm",
            "disabled:cursor-not-allowed disabled:opacity-60",
            "aria-invalid:border-destructive",
          )}
        >
          <span className={cn("min-w-0 flex-1 truncate font-mono", value === "" && "font-sans")}>
            {value === "" ? <span className="text-muted-foreground">{placeholder}</span> : value}
          </span>
          {chosen?.context_length != null && (
            <span className="text-muted-foreground shrink-0 text-xs">
              {contextLabel(chosen.context_length)}
            </span>
          )}
          <ChevronsUpDown className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
        </button>
      </PopoverTrigger>

      <PopoverContent className="w-[min(28rem,90vw)] p-0" align="start">
        <Command shouldFilter>
          <div className="border-border border-b px-3 py-2">
            {/* No `autoFocus`: Radix moves focus into the panel when it opens,
                and the search field is the first thing in it. */}
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder={t("searchModels")}
              className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            />
          </div>

          <Command.List id={listId} className="max-h-72 scrollbar-thin overflow-y-auto p-1">
            {/* Not `Command.Empty`: when something has been typed there *is* an
                option - itself - and an "no matches" line above an offer to use
                what you typed contradicts it. */}
            {loading && (
              <p className="text-muted-foreground px-3 py-6 text-center text-sm">
                {t("readingCatalog")}
              </p>
            )}

            {!loading && options.length === 0 && custom === null && (
              <p className="text-muted-foreground px-3 py-6 text-center text-sm">
                {t("providerPublishesNoList")}
              </p>
            )}

            {custom !== null && (
              <Command.Item
                value={custom}
                onSelect={() => pick(custom)}
                className="aria-selected:bg-accent flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm"
              >
                <Pencil className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">
                  {t.rich("useCustomModel", {
                    name: custom,
                    mono: (chunks) => <span className="font-mono">{chunks}</span>,
                  })}
                </span>
                <Badge variant="outline">{t("notList")}</Badge>
              </Command.Item>
            )}

            {options.map((option) => (
              <Command.Item
                key={option.id}
                // Searched on both, because neither alone is how people look:
                // "opus" is the name and "claude-opus" is the id.
                value={`${option.id} ${option.name}`}
                onSelect={() => pick(option.id)}
                className="aria-selected:bg-accent flex cursor-pointer items-start gap-2 rounded-md px-2 py-2 text-sm"
              >
                <Check
                  className={cn(
                    "mt-0.5 h-3.5 w-3.5 shrink-0",
                    option.id === value ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-xs">{option.id}</span>
                  {option.name !== option.id && (
                    <span className="text-muted-foreground block truncate text-xs">
                      {option.name}
                    </span>
                  )}
                </span>
                {option.context_length != null && (
                  <span className="text-muted-foreground shrink-0 text-xs">
                    {contextLabel(option.context_length)}
                  </span>
                )}
              </Command.Item>
            ))}
          </Command.List>

          {source !== null && options.length > 0 && (
            <p className="text-muted-foreground border-border border-t px-3 py-2 text-xs">
              {source === "live" ? t("listedByProviderJust") : t("deploymentSOwnShortlist")}
            </p>
          )}
        </Command>
      </PopoverContent>
    </Popover>
  );
}
