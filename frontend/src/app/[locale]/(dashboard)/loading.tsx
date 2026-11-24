import { getTranslations } from "next-intl/server";

import { Skeleton } from "@/components/ui";

export default async function DashboardLoading() {
  const t = await getTranslations("nav");

  return (
    <main
      aria-busy="true"
      aria-label={t("loadingPage")}
      className="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-6 p-4 sm:p-6"
    >
      <div className="flex items-center justify-between gap-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-9 w-28" />
      </div>
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
        <Skeleton className="h-32 rounded-xl" />
        <Skeleton className="h-32 rounded-xl" />
        <Skeleton className="h-32 rounded-xl" />
      </section>
      <Skeleton className="h-72 rounded-xl" aria-hidden="true" />
    </main>
  );
}
