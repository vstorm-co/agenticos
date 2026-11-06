"use client";

import { Brain } from "lucide-react";
import { DocumentIcon as Files } from "@/components/icons/product-icons";
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
      <TabsList
        data-tour="memory-views"
        aria-label={t("viewLabel")}
        className="bg-muted/50 [&>button[data-state=active]]:bg-background w-fit shrink-0 gap-1 rounded-lg p-1 shadow-none sm:gap-1 [&>button]:min-h-8 [&>button]:rounded-md [&>button]:border-0 [&>button]:px-3 [&>button]:py-1.5 [&>button[data-state=active]]:shadow-sm"
      >
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
        <MyClaims />
      </TabsContent>
      <TabsContent value="notes" className="mt-0 flex min-h-0 flex-1 flex-col">
        <MyNotes />
      </TabsContent>
    </Tabs>
  );
}
