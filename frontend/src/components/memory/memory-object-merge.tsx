"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, NativeSelect, SearchInput } from "@/components/ui";
import { useMemoryObjectMerges } from "@/hooks/use-memory-operations";
import { usePermissions } from "@/hooks/use-permissions";
import type { MemoryLibrary, MemoryObject } from "@/lib/memory-api";

export function MemoryObjectMerge({
  org,
  library,
  object,
}: {
  org: string;
  library: MemoryLibrary;
  object: MemoryObject;
}) {
  const t = useTranslations("pages.memory.operations");
  const formId = useId();
  const permissions = usePermissions();
  const canMerge = library === "personal" || permissions.scopeOf?.("context:edit") === "all";
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [aliasesPage, setAliasesPage] = useState<string | null>(null);
  const [candidatePage, setCandidatePage] = useState<string | null>(null);
  const { aliases, candidates, merge, undo } = useMemoryObjectMerges(
    org,
    library,
    object.id,
    aliasesPage,
    q.trim(),
    candidatePage,
    canMerge,
  );
  const pending = merge.isPending || undo.isPending;

  return (
    <div className="space-y-3 py-2">
      {aliases.isError && <p role="alert">{t("loadFailed")}</p>}
      {aliases.data?.items.map((entry) => (
        <div key={entry.id} className="flex flex-wrap items-center justify-between gap-2">
          <span>{objectLabel(entry.source)}</span>
          {canMerge && (
            <Button
              size="sm"
              variant="outline"
              aria-label={t("undoNamed", { name: objectLabel(entry.source) })}
              disabled={pending}
              onClick={() => undo.mutate(entry.id)}
            >
              {t("undo")}
            </Button>
          )}
        </div>
      ))}
      {aliases.data?.next_cursor && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setAliasesPage(aliases.data?.next_cursor ?? null)}
        >
          {t("moreAliases")}
        </Button>
      )}
      {aliasesPage && (
        <Button size="sm" variant="ghost" onClick={() => setAliasesPage(null)}>
          {t("firstPage")}
        </Button>
      )}
      {canMerge && (
        <form
          className="space-y-2"
          aria-labelledby={formId}
          onSubmit={(event) => {
            event.preventDefault();
            if (source) merge.mutate(source, { onSuccess: () => setSource("") });
          }}
        >
          <fieldset disabled={pending} className="space-y-2">
            <legend id={formId} className="text-sm font-medium">
              {t("mergeWith", { name: objectLabel(object) })}
            </legend>
            <p className="text-muted-foreground text-xs">{t("mergeHint")}</p>
            <search aria-label={t("findAlias")}>
              <SearchInput
                value={q}
                onChange={(value) => {
                  setQ(value);
                  setSource("");
                  setCandidatePage(null);
                }}
                placeholder={t("findAlias")}
                aria-label={t("findAlias")}
              />
            </search>
            <NativeSelect
              name="alias"
              aria-label={t("chooseAlias")}
              disabled={candidates.isPending || candidates.isError}
              value={source}
              onChange={(event) => setSource(event.target.value)}
              required
            >
              <option value="">{t("chooseAlias")}</option>
              {candidates.data?.items.map((item) => (
                <option value={item.id} key={item.id}>
                  {objectLabel(item)}
                </option>
              ))}
            </NativeSelect>
            {candidates.data?.next_cursor && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setSource("");
                  setCandidatePage(candidates.data?.next_cursor ?? null);
                }}
              >
                {t("moreCandidates")}
              </Button>
            )}
            {candidatePage && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setSource("");
                  setCandidatePage(null);
                }}
              >
                {t("firstPage")}
              </Button>
            )}
          </fieldset>
          {candidates.isError && <p role="alert">{t("loadFailed")}</p>}
          <Button size="sm" type="submit" disabled={!source || pending}>
            {t("merge")}
          </Button>
        </form>
      )}
      {(merge.error || undo.error) && (
        <p role="alert" className="text-destructive">
          {t("mergeFailed")}
        </p>
      )}
    </div>
  );
}

function objectLabel(object: MemoryObject) {
  return object.external_key ? `${object.name} (${object.external_key})` : object.name;
}
