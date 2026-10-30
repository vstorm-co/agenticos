"use client";

import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { Button } from "@/components/ui";
import { FileExplorer } from "@/components/sandboxes/workspace-explorer";
import { useLocalWorkspace } from "@/hooks/use-desktop";
import type { FileSource } from "@/lib/workspace-files";

/** The same approved native reader as chat; this view never uploads a copy. */
export function ProjectFolderExplorer({ root }: { root: string }) {
  const t = useTranslations("projects.localFolder");
  const { workspace, error, refresh } = useLocalWorkspace(root, root);
  const source = useMemo<FileSource>(() => ({ kind: "local", root }), [root]);
  return (
    <div className="flex min-h-[32rem] min-w-0 flex-1 flex-col gap-2">
      <p className="text-muted-foreground text-sm">{t("previewHint")}</p>
      <FileExplorer
        source={source}
        files={workspace ? { ...workspace, truncated: workspace.total >= 500 } : null}
        isLoading={!workspace && !error}
        error={error}
        toolbar={
          <Button size="sm" variant="outline" onClick={() => void refresh()}>
            <RefreshCw className="h-4 w-4" aria-hidden />
            {t("refresh")}
          </Button>
        }
      />
    </div>
  );
}
