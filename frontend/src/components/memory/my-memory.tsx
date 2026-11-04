"use client";

import { Brain, Files } from "lucide-react";
import { useTranslations } from "next-intl";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useOrgStore } from "@/stores";
import { MyClaims } from "./my-claims";
import { MyNotes } from "./my-notes";

export function MyMemory() {
  const t = useTranslations("pages.memory.browser");
  const org = useOrgStore((state) => state.activeOrgId);
  return (
    <Tabs key={org} defaultValue="memories" className="flex min-h-0 flex-1 flex-col gap-4">
      <TabsList data-tour="memory-views" aria-label={t("viewLabel")} className="shrink-0">
        <TabsTrigger value="memories">
          <Brain className="mr-2 size-4" aria-hidden />
          {t("memories")}
        </TabsTrigger>
        <TabsTrigger value="notes">
          <Files className="mr-2 size-4" aria-hidden />
          {t("notes")}
        </TabsTrigger>
      </TabsList>
      <TabsContent value="memories" className="mt-0 flex min-h-0 flex-1 flex-col">
        <MyClaims />
      </TabsContent>
      <TabsContent value="notes" className="mt-0 flex min-h-0 flex-1 flex-col">
        <MyNotes />
      </TabsContent>
    </Tabs>
  );
}
