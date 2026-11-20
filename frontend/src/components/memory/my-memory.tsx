"use client";

import { useTranslations } from "next-intl";
import { useOrgStore } from "@/stores";
import { MyClaims } from "./my-claims";
import { MyNotes } from "./my-notes";

export function MyMemory() {
  const t = useTranslations("pages.memory.browser");
  const org = useOrgStore((state) => state.activeOrgId);
  return (
    <section
      key={org}
      data-tour="memory-views"
      aria-label={t("viewLabel")}
      className="grid min-h-0 flex-1 content-start gap-4 overflow-y-auto xl:grid-cols-2"
    >
      <div className="flex min-w-0 flex-col">
        <MyClaims />
      </div>
      <div className="flex min-w-0 flex-col">
        <MyNotes />
      </div>
    </section>
  );
}
