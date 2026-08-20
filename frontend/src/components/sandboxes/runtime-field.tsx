"use client";

import { useState } from "react";

import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { SandboxRuntime, SandboxRuntimeOption } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

interface RuntimeFieldProps {
  value: string;
  onChange: (alias: string) => void;
  /** What this deployment ships. Offered immediately, without asking a host. */
  catalog: SandboxRuntimeOption[];
  /** What the service said it allows, or null before anybody asked it. */
  allowed: SandboxRuntime[] | null;
  /** Ask the service. Absent when there is nothing to ask with yet. */
  onTest: (() => Promise<void>) | null;
  testing: boolean;
}

/** The empty option's value. A `Select` cannot hold `""`, but it can hold this. */
const SERVICE_DEFAULT = "__service__";

/**
 * Which image an agent gets when its own spec names none.
 *
 * **Populated before anything is probed.** The aliases come from this
 * deployment's own catalogue — the same file the compose files' allowlist is
 * generated from — so the list is complete the moment the form opens, and a
 * select that only filled in after pressing a button was a select nobody
 * would find.
 *
 * Probing is still worth doing and means something narrower: a host can have
 * been started with a different allowlist, so once it has answered, the options
 * it did not name are marked. Before that the field says plainly that nothing
 * has been checked yet, because offering an alias as though it will work is a
 * promise this cannot make.
 *
 * The free-text field stays reachable, and that is not indecision. A service can be
 * restarted with an alias built for it, and a select that cannot express one the
 * operator knows exists is a form that blocks work.
 */
export function RuntimeField({
  value,
  onChange,
  catalog,
  allowed,
  onTest,
  testing,
}: RuntimeFieldProps) {
  const t = useTranslations("sandboxes.runtime");
  const [typing, setTyping] = useState(false);
  const allowedAliases = allowed === null ? null : new Set(allowed.map((one) => one.alias));

  // The catalog, plus anything the service named that the library does not ship -
  // a runtime built for that deployment is exactly the case worth not dropping.
  const options: SandboxRuntimeOption[] = [
    ...catalog,
    ...(allowed ?? [])
      .filter((one) => !catalog.some((entry) => entry.alias === one.alias))
      .map((one) => ({
        alias: one.alias,
        description: one.description,
        image: one.image,
        builds: one.builds,
      })),
  ];
  const known = options.some((entry) => entry.alias === value);

  return (
    <div className="min-w-0 space-y-2">
      <Label htmlFor="connection-runtime">{t("label")}</Label>

      {options.length > 0 && !typing ? (
        <Select
          value={value === "" ? SERVICE_DEFAULT : value}
          onValueChange={(alias) => onChange(alias === SERVICE_DEFAULT ? "" : alias)}
        >
          {/* `min-w-0` and a truncating value: an option label is a sentence
              ("coding — Python with git, ripgrep, fd, jq and uv"), and without
              this the trigger grew to fit it and pushed the dialog wider than the
              viewport. */}
          <SelectTrigger id="connection-runtime" className="w-full min-w-0">
            <SelectValue className="truncate" />
          </SelectTrigger>
          <SelectContent className="max-w-[min(30rem,90vw)]">
            <SelectItem value={SERVICE_DEFAULT}>{t("serviceDefault")}</SelectItem>
            {options.map((runtime) => {
              const missing = allowedAliases !== null && !allowedAliases.has(runtime.alias);
              return (
                <SelectItem
                  key={runtime.alias}
                  value={runtime.alias}
                  // Both badges say something about this option *against the
                  // others* - one image builds, one is missing from the host
                  // that answered. Radix draws an item's `ItemText` in the
                  // closed trigger, where there is nothing left to compare them
                  // with and "not on this host" reads as a claim about the
                  // selection. What that claim was worth is said below the
                  // field instead, about the alias actually chosen.
                  trailing={
                    (runtime.builds || missing) && (
                      <span className="ml-auto flex shrink-0 items-center gap-2 pl-3">
                        {runtime.builds && (
                          <span className="text-muted-foreground text-[10px] uppercase">
                            {t("builds")}
                          </span>
                        )}
                        {missing && (
                          <span className="text-[10px] text-amber-600 uppercase">
                            {t("notOnThisHost")}
                          </span>
                        )}
                      </span>
                    )
                  }
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="font-mono text-xs">{runtime.alias}</span>
                    {runtime.description !== "" && (
                      <span className="text-muted-foreground truncate text-xs">
                        {runtime.description}
                      </span>
                    )}
                  </span>
                </SelectItem>
              );
            })}
            {/* An alias the form is already carrying that neither the library nor
                the service names. Kept rather than dropped: silently clearing a
                stored value while somebody edits an unrelated field is how a
                connection changes runtime with nobody deciding to. */}
            {value !== "" && !known && <SelectItem value={value}>{value}</SelectItem>}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id="connection-runtime"
          value={value}
          placeholder={t("placeholder")}
          onChange={(event) => onChange(event.target.value)}
        />
      )}

      {/* The amber badge in the list says which options this host refused;
          moving it out of `ItemText` means it no longer follows the chosen one
          into the trigger, which is the point - and would have left the one
          case that matters silent, because `connection-dialog.tsx` saves a
          `default_runtime` without checking it against the allowlist. Said
          here instead, about the alias actually selected, where it is a
          sentence rather than a badge with nothing to compare it against. */}
      {allowedAliases !== null && value !== "" && !allowedAliases.has(value) && (
        <p className="text-xs text-amber-600">{t("selectedNotOnThisHost")}</p>
      )}

      {/* One line, not three. What the field is for and what the host said are
          one sentence, and "press Test to find out" stopped being true when the
          dialog started asking on its own (#1039). */}
      <p className="text-muted-foreground text-xs">
        {t("imageAliasAgentGets")}{" "}
        {allowed === null ? t("shipped") : t("allowedCount", { count: allowed.length })}
      </p>

      <div className="flex items-center gap-3">
        {onTest !== null && (
          <Button variant="outline" size="sm" onClick={() => void onTest()} disabled={testing}>
            {testing ? t("asking") : allowed !== null ? t("askAgain") : t("test")}
          </Button>
        )}
        {options.length > 0 && (
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground text-xs underline"
            onClick={() => setTyping(!typing)}
          >
            {typing ? t("pickFromList") : t("typeAlias")}
          </button>
        )}
      </div>
    </div>
  );
}
