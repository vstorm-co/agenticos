"use client";

import { Fragment, useState, type ReactNode } from "react";
import { Crosshair, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { DiffView } from "@/components/authoring/diff-view";
import { Badge, Button, Checkbox, Label, ListCard, Skeleton } from "@/components/ui";
import { useSkillVersion, useSkillVersions, versionPage } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import type { SkillVersionRead } from "@/types/skill-versions";
import { fileChanges } from "./version-diff";

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
 * One column is the reference - the first picked, until another is set - and it is
 * always drawn first, behind a divider; the others keep the order they were picked in
 * and mark what they say differently from it, word by word, as History's diffs do.
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
  const [chosen, setChosen] = useState<string | null>(null);
  const [onlyDifferences, setOnlyDifferences] = useState(false);
  const reference = compared.find((item) => item.key === chosen) ?? compared[0]!;
  return (
    <ListCard
      title={t("title")}
      counted={t("count", { count: compared.length })}
      controls={
        <div className="flex items-center gap-3">
          {compared.length > 1 && (
            <span className="flex items-center gap-1.5">
              <Checkbox
                id="compare-only-differences"
                checked={onlyDifferences}
                onCheckedChange={(value) => setOnlyDifferences(value === true)}
              />
              <Label htmlFor="compare-only-differences" className="text-xs font-normal">
                {t("onlyDifferences")}
              </Label>
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={onClear}>
            {t("clear")}
          </Button>
        </div>
      }
    >
      {compared.length === 1 && (
        <p className="text-muted-foreground px-4 pt-3 text-xs">{t("pickAnother")}</p>
      )}
      <div className="flex gap-3 overflow-x-auto p-4">
        {[reference, ...compared.filter((item) => item.key !== reference.key)].map(
          (item, index) => (
            <Fragment key={item.key}>
              {index === 1 && (
                <div
                  role="separator"
                  aria-orientation="vertical"
                  className="bg-foreground/30 w-0.5 shrink-0 self-stretch rounded-full"
                />
              )}
              <Column
                skillId={skillId}
                item={item}
                reference={index === 0 ? null : reference}
                onlyDifferences={onlyDifferences}
                onReference={() => setChosen(item.key)}
                onRemove={() => onRemove(item)}
              />
            </Fragment>
          ),
        )}
      </div>
    </ListCard>
  );
}

/**
 * One compared version as the column reads it. A version saved since the diagram was
 * drawn pushes it down the list, so the page holding it is found again from the total.
 */
function useComparedVersion(skillId: string, item: Compared) {
  // Kept for the version it was found for: the reference a column reads can change, and
  // another line's newest number would point at the wrong page, or below the first.
  const [moved, setMoved] = useState<{ key: string; newest: number } | null>(null);
  const newest = moved?.key === item.key ? moved.newest : item.newest;
  const page = versionPage(newest, item.number);
  const listed = useSkillVersions(skillId, item.fork, page);
  const id = listed.versions.find((version) => version.number === item.number)?.id ?? null;
  const read = useSkillVersion(skillId, id);
  const loaded = !listed.isLoading && !listed.error;
  if (loaded && id === null && listed.total > newest) {
    setMoved({ key: item.key, newest: listed.total });
  }
  return {
    version: read.version,
    missing: loaded && id === null && listed.total <= newest,
    failed: listed.error ?? read.error,
    retry: () => {
      void listed.refetch();
      if (id !== null) void read.refetch();
    },
  };
}

function Column({
  skillId,
  item,
  reference,
  onlyDifferences,
  onReference,
  onRemove,
}: {
  skillId: string;
  item: Compared;
  /** The column this one is marked against; null for the reference itself. */
  reference: Compared | null;
  onlyDifferences: boolean;
  onReference: () => void;
  onRemove: () => void;
}) {
  const t = useTranslations("skills.page.compare");
  const tErrors = useTranslations("errors");
  const own = useComparedVersion(skillId, item);
  // The reference is read again here; the query is shared, so it is one request.
  const against = useComparedVersion(skillId, reference ?? item);
  const base = reference === null ? null : against.version;
  const version = own.version;
  // A column is unreadable when its own version is, or the reference it is marked against.
  const broken =
    own.failed || own.missing
      ? own
      : reference !== null && (against.failed || against.missing)
        ? against
        : null;
  return (
    <section
      aria-label={item.name}
      className={cn(
        "flex w-96 shrink-0 flex-col gap-3 rounded-xl p-3",
        reference === null ? "border-primary bg-primary/5 border-2" : "bg-card border",
      )}
    >
      <header className="flex items-center justify-between gap-2">
        <h3 className="truncate font-mono text-sm font-medium">{item.name}</h3>
        <span className="flex shrink-0 items-center gap-1.5">
          {reference === null ? (
            <Badge>{t("reference")}</Badge>
          ) : (
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onReference}>
              <Crosshair className="size-3.5" aria-hidden />
              {t("setReference")}
            </Button>
          )}
          <button
            type="button"
            aria-label={t("remove", { version: item.name })}
            className="text-muted-foreground hover:text-foreground"
            onClick={onRemove}
          >
            <X className="size-4" aria-hidden />
          </button>
        </span>
      </header>
      {broken ? (
        <div role="alert" className="space-y-2 text-sm">
          <p className="text-destructive">
            {t("unreadable")}
            {broken.failed ? ` ${getErrorMessage(broken.failed, tErrors)}` : ""}
          </p>
          <Button variant="outline" size="sm" onClick={broken.retry}>
            {t("retry")}
          </Button>
        </div>
      ) : version === undefined || (reference !== null && base === undefined) ? (
        <Skeleton className="h-40 w-full" aria-label={t("loading")} />
      ) : (
        <Sections version={version} base={base ?? null} onlyDifferences={onlyDifferences} />
      )}
    </section>
  );
}

/** A version's three parts; against a reference, each marked where it differs. */
function Sections({
  version,
  base,
  onlyDifferences,
}: {
  version: SkillVersionRead;
  base: SkillVersionRead | null;
  onlyDifferences: boolean;
}) {
  const t = useTranslations("skills.page.compare");
  const files = base ? fileChanges(base.resources, version.resources) : null;
  const filesSame =
    files !== null && files.added.length + files.removed.length + files.changed.length === 0;
  // Said the same as the reference, a part reads as it is; said differently, as a diff.
  const text = (before: string | undefined, after: string, plain: ReactNode) =>
    base === null || before === after ? plain : <DiffView before={before ?? ""} after={after} />;
  return (
    <>
      <Part
        title={t("description")}
        same={base !== null && base.description === version.description}
        onlyDifferences={onlyDifferences}
      >
        {text(
          base?.description,
          version.description,
          <p className="text-sm">{version.description}</p>,
        )}
      </Part>
      <Part
        title={t("instructions")}
        same={base !== null && base.content === version.content}
        onlyDifferences={onlyDifferences}
      >
        {text(
          base?.content,
          version.content,
          <pre className="bg-muted max-h-80 overflow-auto rounded-md p-2 text-xs whitespace-pre-wrap">
            {version.content}
          </pre>,
        )}
      </Part>
      <Part title={t("files")} same={filesSame} onlyDifferences={onlyDifferences}>
        {version.resources.length + (files?.removed.length ?? 0) === 0 ? (
          <p className="text-muted-foreground text-xs">{t("noFiles")}</p>
        ) : (
          <ul className="space-y-1 text-xs">
            {version.resources.map((file) => {
              const mark = files?.added.includes(file.name)
                ? "added"
                : files?.changed.includes(file.name)
                  ? "changed"
                  : null;
              return (
                <li
                  key={file.name}
                  className={cn(
                    mark === "added" && "text-emerald-700 dark:text-emerald-400",
                    mark === "changed" && "text-warning",
                  )}
                >
                  <span className="font-mono">{file.name}</span>
                  {mark && <span className="ml-1.5">{t(`file.${mark}`)}</span>}
                  {file.description && (
                    <span className="text-muted-foreground block">{file.description}</span>
                  )}
                </li>
              );
            })}
            {files?.removed.map((name) => (
              <li key={`removed:${name}`} className="text-destructive">
                <del className="font-mono">{name}</del>
                <span className="ml-1.5">{t("file.removed")}</span>
              </li>
            ))}
          </ul>
        )}
      </Part>
    </>
  );
}

function Part({
  title,
  same,
  onlyDifferences,
  children,
}: {
  title: string;
  /** Said the same as the reference: nothing to mark, and folded with only the differences. */
  same: boolean;
  onlyDifferences: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("skills.page.compare");
  return (
    <div className="space-y-1">
      <h4 className="text-muted-foreground text-xs font-medium">
        {title}
        {same && <span className="ml-1.5 font-normal italic">{t("sameAsReference")}</span>}
      </h4>
      {!(same && onlyDifferences) && children}
    </div>
  );
}
