"use client";

import { use } from "react";
import { GraduationCap } from "lucide-react";
import { useTranslations } from "next-intl";

import { TeachingReview } from "@/components/browser-teaching/teaching-review";
import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState, LoadingState } from "@/components/states";
import { useBrowserTeaching } from "@/hooks/use-browser-teaching";

interface PageProps {
  params: Promise<{ sessionId: string }>;
}

/**
 * Review one Teach a task recording and turn it into a skill proposal (#113).
 *
 * Only the person who recorded it can read it; anyone else gets the same answer
 * as for a recording that does not exist. The proposal it creates is decided
 * with the other skill changes on the Skills page.
 */
export default function BrowserTeachingPage({ params }: PageProps) {
  const { sessionId } = use(params);
  const t = useTranslations("browserTeaching");
  const teaching = useBrowserTeaching(sessionId);

  return (
    <div className="mx-auto w-full max-w-4xl min-w-0 space-y-4">
      <PageHeader
        title={teaching.teaching?.title || t("title")}
        description={t("description")}
        descriptionMode="summary"
      />
      {teaching.isLoading ? (
        <LoadingState variant="pending" />
      ) : teaching.teaching === undefined ? (
        <EmptyState icon={GraduationCap} title={t("missingTitle")} description={t("missingBody")} />
      ) : (
        <TeachingReview
          key={teaching.identity}
          teaching={teaching.teaching}
          isSaving={teaching.isSaving}
          isProposing={teaching.isProposing}
          saveReview={teaching.saveReview}
          propose={teaching.propose}
        />
      )}
    </div>
  );
}
