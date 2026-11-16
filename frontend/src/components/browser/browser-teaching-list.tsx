"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button, Card, CardContent } from "@/components/ui";
import { PageHeader } from "@/components/dashboard/page-header";
import { useTeachingAudience, useTeachingList } from "@/hooks/use-browser-teaching-settings";
import { ROUTES } from "@/lib/constants";
import { TeachingError, TeachingStatus, TeachingTime } from "./browser-teaching-status";

export function BrowserTeachingList() {
  const audience = useTeachingAudience();
  return <TeachingListContent key={JSON.stringify([audience.actor, audience.organization])} />;
}
function TeachingListContent() {
  const t = useTranslations("browserTeaching");
  const locale = useLocale();
  const list = useTeachingList();
  const items = list.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-5">
      <PageHeader
        title={t("listTitle")}
        description={t("listDescription")}
        secondaryActions={
          <Button asChild variant="outline">
            <Link href={`/${locale}${ROUTES.SKILLS}`}>{t("backToSkills")}</Link>
          </Button>
        }
      />
      <section data-tour="teaching-list" aria-label={t("listTitle")} className="space-y-4">
        <p className="text-muted-foreground max-w-3xl text-sm">{t("startFromBrowser")}</p>
        {list.isPending ? (
          <p role="status">{t("loading")}</p>
        ) : list.error ? (
          <TeachingError error={list.error} />
        ) : items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("emptyList")}</p>
        ) : (
          items.map((session) => (
            <Card key={session.id}>
              <CardContent className="flex flex-wrap items-start justify-between gap-4 p-4">
                <div className="min-w-0 flex-1 space-y-2">
                  <h2 className="font-medium break-words">
                    {session.title || t("expiredCapture")}
                  </h2>
                  <TeachingStatus session={session} />
                  <p className="text-muted-foreground text-xs break-words">
                    {session.allowed_origins.join(", ")}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {t("createdAt")} <TeachingTime value={session.created_at} />
                  </p>
                </div>
                <Button asChild variant="outline">
                  <Link href={`/${locale}${ROUTES.SKILL_TEACHING(session.id)}`}>
                    {t("openCapture")}
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ))
        )}
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={list.isFetching} onClick={() => void list.restart()}>
            {t("refreshList")}
          </Button>
          {list.hasNextPage && !list.error && (
            <Button
              variant="outline"
              disabled={list.isFetching}
              onClick={() => void list.fetchNextPage()}
            >
              {t("loadMore")}
            </Button>
          )}
        </div>
      </section>
    </div>
  );
}
