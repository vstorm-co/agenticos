"use client";

import { BookOpen, Download, FileText } from "lucide-react";

import { useSkillLibrary } from "@/hooks";
import { Button, Pager, SearchInput, useListControls } from "@/components/ui";
import { LoadingState } from "@/components/states";
import { formatSize } from "@/components/skills/skill-files";
import { useTranslations } from "next-intl";

/**
 * The skills this deployment ships with, ready to copy in.
 *
 * A copy, not a link: from the moment it is installed it is an ordinary skill
 * the organization owns and edits, which is the whole point of skills - a
 * support lead fixes the refund policy without a deploy. A live reference back
 * to the shipped folder would take that away.
 *
 * The library is bundled in the repository rather than fetched from a registry.
 * Each folder is the same small promise the MCP catalog makes: somebody looked
 * at it. What that costs is that adding one is a deploy.
 */
export function SkillLibraryGallery({ canInstall }: { canInstall: boolean }) {
  const t = useTranslations("skills");
  const { library, isLoading, install } = useSkillLibrary();
  // Only what is not already here. The section answers "what else could I
  // have", and a card for something the organization installed last week
  // answers nothing - it was a second copy of the list above, greyed out, with
  // an "Already installed" button that does nothing when pressed.
  const available = library.filter((entry) => !entry.installed);
  // Client-side: the library is compiled into the deployment, so the whole set
  // is already here and a round trip per keystroke would be the slower design.
  const list = useListControls({
    items: available,
    matches: (entry, query) =>
      entry.name.toLowerCase().includes(query) || entry.description.toLowerCase().includes(query),
  });

  if (isLoading) return <LoadingState variant="skeleton-cards" />;
  if (available.length === 0) return null;

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm font-medium">{t("readyMadeSkills")}</p>
        <p className="text-muted-foreground text-xs">{t("writtenPlatformCopiedInto")}</p>
      </div>

      {/* Only once the shelf is long enough to be worth searching - a box over
          three cards is a control that reads as a missing list. */}
      {available.length > 8 && (
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchLibrary")} />
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {list.visible.map((entry) => (
          <div
            key={entry.key}
            className="border-border bg-card flex flex-col rounded-xl border p-4"
          >
            <span className="flex items-center gap-2">
              <BookOpen className="text-muted-foreground h-4 w-4 shrink-0" />
              <span className="font-mono text-sm font-medium">{entry.name}</span>
            </span>

            <p className="text-muted-foreground mt-2 line-clamp-3 flex-1 text-sm">
              {entry.description}
            </p>

            {entry.resources.length > 0 && (
              <ul className="mt-3 space-y-1">
                {entry.resources.map((resource) => (
                  <li
                    key={resource.name}
                    className="text-muted-foreground flex items-center gap-1.5 font-mono text-xs"
                  >
                    <FileText className="h-3 w-3 shrink-0" />
                    <span className="min-w-0 truncate">{resource.name}</span>
                    <span className="shrink-0">{formatSize(resource.size_bytes)}</span>
                  </li>
                ))}
              </ul>
            )}

            {canInstall && (
              <Button
                variant="outline"
                size="sm"
                className="mt-4 self-start"
                disabled={install.isPending}
                onClick={() => install.mutate(entry.key)}
              >
                <Download className="h-4 w-4" />
                {t("install")}
              </Button>
            )}
          </div>
        ))}
      </div>

      <Pager
        page={list.page}
        pageCount={list.pageCount}
        matched={list.matched}
        total={list.total}
        onPage={list.setPage}
        noun="ready-made skills"
      />
    </div>
  );
}
