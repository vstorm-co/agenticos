"use client";

import { useState } from "react";
import { Brain } from "lucide-react";
import { DocumentIcon as Files } from "@/components/icons/product-icons";
import { useTranslations } from "next-intl";
import { Button, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { useOrgStore } from "@/stores";
import { MyClaims } from "./my-claims";
import { MemorySourceSettings } from "./memory-source-settings";
import { MyNotes } from "./my-notes";
import {
  MemoryObjectLibrary,
  SharedMemoryClaims,
  SharedMemoryNotes,
} from "./memory-object-library";
import type { MemoryLibrary } from "@/lib/memory-api";

export function MyMemory({
  initialObject,
  initialLibrary,
}: {
  initialObject?: string;
  initialLibrary?: MemoryLibrary;
}) {
  const org = useOrgStore((state) => state.activeOrgId);
  const [entryOrg] = useState(org);
  return (
    <MemoryWorkspace
      key={org}
      initialObject={entryOrg === org ? initialObject : undefined}
      initialLibrary={entryOrg === org ? initialLibrary : undefined}
    />
  );
}

function MemoryWorkspace({
  initialObject,
  initialLibrary,
}: {
  initialObject?: string;
  initialLibrary?: MemoryLibrary;
}) {
  const t = useTranslations("pages.memory.browser");
  const libraryText = useTranslations("pages.memory.library");
  const [library, setLibrary] = useState<MemoryLibrary>(initialLibrary ?? "personal");
  const [objects, setObjects] = useState(Boolean(initialObject));
  const [linkedObject, setLinkedObject] = useState(initialObject);
  const permissions = usePermissions();
  const canViewShared = permissions.can("context:view");
  const canShare = permissions.scopeOf?.("context:edit") === "all";
  const canManageSource = canShare && permissions.can("connections:manage");
  const activeLibrary = canViewShared ? library : "personal";
  const can = permissions.can;
  const canViewAgents = can("agents:view");
  const { agents } = useAgents({ includeArchived: true, enabled: canViewAgents });
  const visibleAgents = canViewAgents ? agents : [];
  return (
    <Tabs defaultValue="memories" className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {canViewShared && (
          <div role="group" aria-label={libraryText("scopeLabel")} className="flex gap-1">
            <Button
              size="sm"
              variant={activeLibrary === "personal" ? "secondary" : "ghost"}
              aria-pressed={activeLibrary === "personal"}
              onClick={() => {
                setLibrary("personal");
                setLinkedObject(undefined);
              }}
            >
              {libraryText("personal")}
            </Button>
            <Button
              size="sm"
              variant={activeLibrary === "organization" ? "secondary" : "ghost"}
              aria-pressed={activeLibrary === "organization"}
              onClick={() => {
                setLibrary("organization");
                setLinkedObject(undefined);
              }}
            >
              {libraryText("organization")}
            </Button>
          </div>
        )}
        <TabsList data-tour="memory-views" aria-label={t("viewLabel")} className="w-fit shrink-0">
          <TabsTrigger value="memories">
            <Brain className="size-4" aria-hidden />
            {t("memories")}
          </TabsTrigger>
          <TabsTrigger value="notes">
            <Files className="size-4" aria-hidden />
            {t("notes")}
          </TabsTrigger>
        </TabsList>
        {canManageSource && activeLibrary === "organization" && <MemorySourceSettings />}
      </div>
      <TabsContent value="memories" className="mt-0 flex min-h-0 flex-1 flex-col">
        <div className="mb-2 flex gap-2" role="group" aria-label={libraryText("memoriesView")}>
          <Button
            size="sm"
            variant={!objects ? "secondary" : "ghost"}
            aria-pressed={!objects}
            onClick={() => setObjects(false)}
          >
            {libraryText("claims")}
          </Button>
          <Button
            size="sm"
            variant={objects ? "secondary" : "ghost"}
            aria-pressed={objects}
            onClick={() => setObjects(true)}
          >
            {libraryText("objects")}
          </Button>
        </div>
        {objects ? (
          <MemoryObjectLibrary
            key={activeLibrary}
            library={activeLibrary}
            initialObject={activeLibrary === initialLibrary ? linkedObject : undefined}
          />
        ) : activeLibrary === "personal" ? (
          <MyClaims agents={visibleAgents} canShare={canShare} />
        ) : (
          <SharedMemoryClaims />
        )}
      </TabsContent>
      <TabsContent value="notes" className="mt-0 flex min-h-0 flex-1 flex-col">
        {activeLibrary === "personal" ? (
          <MyNotes agents={visibleAgents} canShare={canShare} />
        ) : (
          <SharedMemoryNotes />
        )}
      </TabsContent>
    </Tabs>
  );
}
