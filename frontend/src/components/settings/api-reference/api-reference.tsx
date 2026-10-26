"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { ErrorState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui";
import { usePublicOpenApi } from "@/hooks";
import { buildReference, humanizeTag, matchesQuery } from "@/lib/openapi/reference";
import { ApiOperation } from "./api-operation";
import { ApiReferenceIntro } from "./api-reference-intro";

/**
 * Every endpoint an organization key can call, read from this deployment's own
 * public OpenAPI document and grouped the way the document tags them.
 */
export function ApiReference() {
  const t = useTranslations("apiReference");
  const tc = useTranslations("common");
  const ts = useTranslations("states");
  const { apiUrl } = usePublicConfig();
  const { document, isLoading, error, refetch } = usePublicOpenApi();
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    if (!document) return [];
    return buildReference(document)
      .map((group) => ({
        ...group,
        operations: group.operations.filter((op) => matchesQuery(op, query)),
      }))
      .filter((group) => group.operations.length > 0);
  }, [document, query]);

  if (isLoading)
    return (
      <div className="space-y-6" role="status" aria-label={ts("loading")}>
        <ApiReferenceIntro baseUrl={apiUrl} version={undefined} />
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start" aria-hidden>
          <div className="space-y-3 lg:w-56 lg:shrink-0">
            <Skeleton className="h-9 w-full" />
            {[0, 1, 2].map((group) => (
              <Skeleton key={group} className="h-7 w-full" />
            ))}
          </div>
          <div className="min-w-0 flex-1 space-y-6">
            {[0, 1, 2].map((group) => (
              <section
                key={group}
                className="border-border bg-card space-y-3 rounded-xl border px-3 py-3"
              >
                <Skeleton className="h-5 w-40" />
                {[0, 1, 2].map((row) => (
                  <Skeleton key={row} className="h-10 w-full" />
                ))}
              </section>
            ))}
          </div>
        </div>
      </div>
    );
  if (error || !document) {
    return (
      <ErrorState
        title={t("loadError")}
        cta={{ label: tc("retry"), onClick: () => void refetch() }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <ApiReferenceIntro baseUrl={apiUrl} version={document.info.version} />
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <nav aria-label={t("groups")} className="space-y-3 lg:sticky lg:top-4 lg:w-56 lg:shrink-0">
          <div className="relative">
            <Search
              className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("search")}
              aria-label={t("search")}
              className="pl-8"
            />
          </div>
          <ul className="flex flex-wrap gap-1 lg:flex-col lg:gap-0.5">
            {groups.map((group) => (
              <li key={group.tag}>
                <a
                  href={`#group-${group.tag}`}
                  className="text-muted-foreground hover:text-foreground hover:bg-accent flex items-center justify-between gap-3 rounded-md px-2 py-1 text-sm"
                >
                  <span>{humanizeTag(group.tag)}</span>
                  <span className="text-xs tabular-nums">{group.operations.length}</span>
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 flex-1 space-y-6">
          {groups.length === 0 && (
            <p className="text-muted-foreground py-10 text-center text-sm">
              {t("noMatch", { query })}
            </p>
          )}
          {groups.map((group) => (
            <section
              key={group.tag}
              id={`group-${group.tag}`}
              className="border-border bg-card scroll-mt-4 rounded-xl border px-3 py-3"
            >
              <h2 className="flex items-baseline gap-2 px-2 pb-2 text-sm font-semibold">
                {humanizeTag(group.tag)}
                <span className="text-muted-foreground text-xs font-normal">
                  {t("count", { count: group.operations.length })}
                </span>
              </h2>
              {group.operations.map((operation) => (
                <ApiOperation key={operation.id} operation={operation} baseUrl={apiUrl} />
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
