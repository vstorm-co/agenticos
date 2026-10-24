"use client";

import { useTranslations } from "next-intl";

import { AddPhone } from "@/components/mobile/add-phone";
import { SectionHeading } from "@/components/ui";

/** The mobile app: pairing a phone by QR (#2097). */
export default function MobileAppPage() {
  const t = useTranslations("mobile.settings");

  return (
    <div className="space-y-6">
      <SectionHeading title={t("heading")} description={t("headingHint")} />
      <AddPhone />
    </div>
  );
}
