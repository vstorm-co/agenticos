"use client";

import { X } from "lucide-react";
import { useId, useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Label,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { useMcpCatalogPage, MCP_PAGE_SIZE } from "@/hooks/use-mcp-servers";
import { useSkillGallery } from "@/hooks/use-skill-gallery";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import type { CatalogPolicy } from "@/lib/console-experience-api";

/** The picker offers the caller's catalog; the API enforces every parent ceiling again. */
export function ConsoleCatalogControls({
  kind,
  value,
  disabled,
  onSave,
  onDirtyChange,
}: {
  kind: "mcp_gallery" | "skill_gallery";
  value: CatalogPolicy | null | undefined;
  disabled: boolean;
  onSave: (value: CatalogPolicy | null, onSaved: () => void) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const id = useId();
  const t = useTranslations("consoleExperience.catalogs");
  const common = useTranslations("common");
  const [draft, setDraft] = useState<CatalogPolicy | null | undefined>(undefined);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const policy = draft === undefined ? value : draft;
  const dirty = draft !== undefined;
  const choosing = policy?.mode === "allow-list";
  const mcp = useMcpCatalogPage(search, "", "", page, choosing && kind === "mcp_gallery");
  const skills = useSkillGallery(choosing && kind === "skill_gallery");
  const options =
    kind === "mcp_gallery"
      ? mcp.servers
      : skills.industries
          .flatMap((industry) => industry.skills)
          .filter((entry) =>
            `${entry.name} ${entry.description}`
              .toLocaleLowerCase()
              .includes(search.toLocaleLowerCase()),
          );
  const loading = kind === "mcp_gallery" ? mcp.isLoading : skills.isLoading;
  const failed = kind === "mcp_gallery" ? !!mcp.error : skills.isError;
  const selected = policy?.keys ?? [];
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useUnsavedChanges(id, { dirty, discard: () => setDraft(undefined) });
  const choose = (key: string, checked: boolean) =>
    setDraft({
      mode: "allow-list",
      keys: checked ? [...selected, key] : selected.filter((item) => item !== key),
    });
  return (
    <fieldset className="space-y-3 border-t pt-4" disabled={disabled}>
      <legend className="px-1 text-sm font-medium">{t(kind)}</legend>
      <p className="text-muted-foreground text-xs leading-5">{t("hint")}</p>
      <Label htmlFor={id} className="sr-only">
        {t(kind)}
      </Label>
      <Select
        value={policy?.mode ?? "inherit"}
        disabled={disabled}
        onValueChange={(mode) => {
          if (mode === "inherit") setDraft(null);
          else if (mode === "all" || mode === "available" || mode === "allow-list")
            setDraft({ mode, keys: [] });
        }}
      >
        <SelectTrigger id={id} className="w-full sm:max-w-sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="inherit">{t("inherit")}</SelectItem>
          <SelectItem value="all">{t("all")}</SelectItem>
          <SelectItem value="available">{t(`${kind}Available`)}</SelectItem>
          <SelectItem value="allow-list">{t("allowList")}</SelectItem>
        </SelectContent>
      </Select>
      {choosing && (
        <div className="space-y-3">
          <SearchInput
            value={search}
            onChange={(next) => {
              setSearch(next);
              setPage(0);
            }}
            placeholder={common("search")}
          />
          <p className="text-muted-foreground text-xs">
            {t("selected", { count: selected.length })}
          </p>
          {selected.length >= 512 && (
            <p className="text-muted-foreground text-xs">{t("limit", { count: 512 })}</p>
          )}
          {selected.length === 0 && (
            <p className="text-muted-foreground text-xs">{t("emptySelection")}</p>
          )}
          {selected.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {selected.map((key) => (
                <li key={key} className="max-w-full min-w-0">
                  <Button
                    variant="outline"
                    className="max-w-full gap-2"
                    size="sm"
                    type="button"
                    disabled={disabled}
                    onClick={() => choose(key, false)}
                    aria-label={t("remove", {
                      name: options.find((item) => item.key === key)?.name ?? key,
                    })}
                  >
                    <span className="truncate">
                      {options.find((item) => item.key === key)?.name ?? key}
                    </span>
                    <X className="size-3 shrink-0" aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {failed ? (
            <ErrorState
              cta={{
                label: common("retry"),
                onClick: () => {
                  void (kind === "mcp_gallery" ? mcp.refetch() : skills.refetch());
                },
              }}
            />
          ) : loading ? (
            <LoadingState variant="pending" />
          ) : (
            <div className="max-h-72 overflow-y-auto rounded-lg border p-2">
              <div className="space-y-1">
                {options.map((option) => (
                  <div key={option.key} className="flex min-h-11 items-center gap-3">
                    <Checkbox
                      id={`${id}-${option.key}`}
                      checked={selected.includes(option.key)}
                      disabled={
                        disabled || (!selected.includes(option.key) && selected.length >= 512)
                      }
                      onCheckedChange={(checked) => choose(option.key, checked === true)}
                    />
                    <Label
                      htmlFor={`${id}-${option.key}`}
                      className="flex min-h-11 min-w-0 flex-1 items-center text-sm font-normal break-words"
                    >
                      {option.name}
                    </Label>
                  </div>
                ))}
                {options.length === 0 && (
                  <p className="text-muted-foreground p-3 text-sm">{t("empty")}</p>
                )}
              </div>
            </div>
          )}
          {kind === "mcp_gallery" && (
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={disabled || page === 0 || mcp.isFetching}
                onClick={() => setPage(page - 1)}
              >
                {t("previous")}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={disabled || (page + 1) * MCP_PAGE_SIZE >= mcp.total || mcp.isFetching}
                onClick={() => setPage(page + 1)}
              >
                {common("next")}
              </Button>
            </div>
          )}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          disabled={disabled || !dirty}
          onClick={() => setDraft(undefined)}
        >
          {t("discard")}
        </Button>
        <Button
          type="button"
          disabled={disabled || !dirty}
          onClick={() => {
            if (draft !== undefined) onSave(draft, () => setDraft(undefined));
          }}
        >
          {common("save")}
        </Button>
      </div>
    </fieldset>
  );
}
