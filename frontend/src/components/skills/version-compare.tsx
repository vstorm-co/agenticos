"use client";

import { useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, ListCard, PAGE_SIZE, Skeleton } from "@/components/ui";
import { useSkillVersion, useSkillVersions } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";

/** A version put in the comparison, by its line and number. */
export interface Compared {
  key: string;
  /** The fork the version belongs to; null on main. */
  fork: string | null;
  number: number;
  /** The line's newest number, which says the page of its list the version is on. */
  newest: number;
  /** How the diagram named it. */
  name: string;
}

/**
 * The versions a reader picked on the diagram, side by side in the order picked:
 * each one's description, instructions and files, read the way the skill serves them.
 */
export function VersionCompare({
  skillId,
  compared,
  onRemove,
  onClear,
}: {
  skillId: string;
  compared: Compared[];
  onRemove: (item: Compared) => void;
  onClear: () => void;
}) {
  const t = useTranslations("skills.page.compare");
  return (
    <ListCard
      title={t("title")}
      counted={t("count", { count: compared.length })}
      controls={
        <Button variant="ghost" size="sm" onClick={onClear}>
          {t("clear")}
        </Button>
      }
    >
      {compared.length === 1 && (
        <p className="text-muted-foreground px-4 pt-3 text-xs">{t("pickAnother")}</p>
      )}
      <div className="flex gap-3 overflow-x-auto p-4">
        {compared.map((item) => (
          <Column key={item.key} skillId={skillId} item={item} onRemove={() => onRemove(item)} />
        ))}
      </div>
    </ListCard>
  );
}

function Column({
  skillId,
  item,
  onRemove,
}: {
  skillId: string;
  item: Compared;
  onRemove: () => void;
}) {
  const t = useTranslations("skills.page.compare");
  const tErrors = useTranslations("errors");
  // Versions are listed newest first, so the page holding one follows from its number.
  const [newest, setNewest] = useState(item.newest);
  const page = Math.floor((newest - item.number) / PAGE_SIZE);
  const listed = useSkillVersions(skillId, item.fork, page);
  const id = listed.versions.find((version) => version.number === item.number)?.id ?? null;
  const read = useSkillVersion(skillId, id);
  const loaded = !listed.isLoading && !listed.error;
  // A version saved since the diagram was drawn pushes this one down the list.
  if (loaded && id === null && listed.total > newest) setNewest(listed.total);
  const missing = loaded && id === null && listed.total <= newest;
  const failed = listed.error ?? read.error;
  const version = read.version;
  return (
    <section
      aria-label={item.name}
      className="bg-card flex w-80 shrink-0 flex-col gap-3 rounded-xl border p-3"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 className="truncate font-mono text-sm font-medium">{item.name}</h3>
        <button
          type="button"
          aria-label={t("remove", { version: item.name })}
          className="text-muted-foreground hover:text-foreground"
          onClick={onRemove}
        >
          <X className="size-4" aria-hidden />
        </button>
      </header>
      {failed || missing ? (
        <div role="alert" className="space-y-2 text-sm">
          <p className="text-destructive">
            {t("unreadable")}
            {failed ? ` ${getErrorMessage(failed, tErrors)}` : ""}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void listed.refetch();
              if (id !== null) void read.refetch();
            }}
          >
            {t("retry")}
          </Button>
        </div>
      ) : version === undefined ? (
        <Skeleton className="h-40 w-full" aria-label={t("loading")} />
      ) : (
        <>
          <Part title={t("description")}>
            <p className="text-sm">{version.description}</p>
          </Part>
          <Part title={t("instructions")}>
            <pre className="bg-muted max-h-80 overflow-auto rounded-md p-2 text-xs whitespace-pre-wrap">
              {version.content}
            </pre>
          </Part>
          <Part title={t("files")}>
            {version.resources.length === 0 ? (
              <p className="text-muted-foreground text-xs">{t("noFiles")}</p>
            ) : (
              <ul className="space-y-1 text-xs">
                {version.resources.map((file) => (
                  <li key={file.name}>
                    <span className="font-mono">{file.name}</span>
                    {file.description && (
                      <span className="text-muted-foreground block">{file.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Part>
        </>
      )}
    </section>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <h4 className="text-muted-foreground text-xs font-medium">{title}</h4>
      {children}
    </div>
  );
}
