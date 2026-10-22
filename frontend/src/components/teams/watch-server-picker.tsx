"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { Checkbox, Input } from "@/components/ui";
import { useMcpCatalog } from "@/hooks";

type Reach = "all" | "some";

/**
 * Which catalog servers people here may have watched (#2301): every one, or the
 * ones ticked. `null` is every one - a server added to the catalog later is then
 * allowed too, which a list ticked today could not say.
 */
export function WatchServerPicker({
  labelledBy,
  value,
  onChange,
  disabled,
}: {
  labelledBy: string;
  value: string[] | null;
  onChange: (next: string[] | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("teams.proactive");
  const { servers } = useMcpCatalog();
  const [query, setQuery] = useState("");
  const shown = servers.filter((server) =>
    server.name.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const picked = new Set(value ?? []);

  return (
    <div className="space-y-3">
      <ChoiceGroup<Reach>
        labelledBy={labelledBy}
        value={value === null ? "all" : "some"}
        options={[
          { value: "all", label: t("watchServersAll") },
          { value: "some", label: t("watchServersSome") },
        ]}
        onChange={(reach) => onChange(reach === "all" ? null : [])}
        disabled={disabled}
      />
      {value !== null && (
        <div className="space-y-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("watchServersSearch")}
            aria-label={t("watchServersSearch")}
            disabled={disabled}
          />
          <ul className="bg-muted/40 max-h-56 space-y-0.5 overflow-y-auto rounded-xl p-1.5">
            {shown.map((server) => (
              <li key={server.key}>
                <label className="hover:bg-background flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm">
                  <Checkbox
                    checked={picked.has(server.key)}
                    disabled={disabled}
                    onCheckedChange={(on) =>
                      onChange(
                        on === true
                          ? [...picked, server.key].sort()
                          : [...picked].filter((key) => key !== server.key),
                      )
                    }
                  />
                  <McpServerIcon icon={server.icon} name={server.name} url={server.url} />
                  <span className="truncate">{server.name}</span>
                </label>
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground text-xs">
            {t("watchServersPicked", { count: picked.size })}
          </p>
        </div>
      )}
    </div>
  );
}
