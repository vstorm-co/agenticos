"use client";

import { Brain } from "lucide-react";
import { DocumentIcon as Files } from "@/components/icons/product-icons";
import { useTranslations } from "next-intl";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { useOrgStore } from "@/stores";
import { MyClaims } from "./my-claims";
import { MyNotes } from "./my-notes";

export function MyMemory() {
  const t = useTranslations("pages.memory.browser");
  const org = useOrgStore((state) => state.activeOrgId);
  const { can } = usePermissions();
  const canViewAgents = can("agents:view");
  const { agents } = useAgents({ includeArchived: true, enabled: canViewAgents });
  const visibleAgents = canViewAgents ? agents : [];
  return (
    <Tabs key={org} defaultValue="memories" className="flex min-h-0 flex-1 flex-col gap-4">
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
      <TabsContent value="memories" className="mt-0 flex min-h-0 flex-1 flex-col">
        <MyClaims agents={visibleAgents} />
      </TabsContent>
      <TabsContent value="notes" className="mt-0 flex min-h-0 flex-1 flex-col">
        <MyNotes agents={visibleAgents} />
      </TabsContent>
    </Tabs>
  );
}
