import Link from "next/link";

import { ROUTES } from "@/lib/constants";
import { useTranslations } from "next-intl";

/** The deployment's name, resolved by the page above and interpolated into the text. */
interface LegalBodyProps {
  appName: string;
}

export function PrivacyBodyEn({ appName }: LegalBodyProps) {
  const t = useTranslations("legal");
  return (
    <>
      <p>{t("privacyIntro", { appName })}</p>

      <h2>{t("n1WhatWeCollect")}</h2>
      <h3>{t("informationYouProvide")}</h3>
      <ul>
        <li>
          <strong>{t("accountInfo")}</strong>
          {t("nameEmailHashedPassword")}
        </li>
        <li>
          <strong>{t("customerData")}</strong>
          {t("promptsDocumentsYouUpload")}
        </li>
        <li>
          <strong>{t("billingInfo")}</strong>
          {t("handledByOurPayment")}
        </li>
        <li>
          <strong>{t("supportCorrespondence")}</strong>
          {t("whenYouEmailUs")}
        </li>
      </ul>
      <h3>{t("informationCollectedAutomatically")}</h3>
      <ul>
        <li>
          <strong>{t("usageData")}</strong>
          {t("requestPathsResponseTimes")}
        </li>
        <li>
          <strong>{t("deviceData")}</strong>
          {t("browserOsIpAddress")}
        </li>
        <li>
          {t.rich("cookiesSeeOurPolicy", {
            strong: (chunks) => <strong>{chunks}</strong>,
            policy: (chunks) => <Link href={ROUTES.LEGAL_COOKIES}>{chunks}</Link>,
          })}
        </li>
      </ul>

      <h2>{t("n2WhyWeUse")}</h2>
      <ul>
        <li>{t("operateMaintainImproveService")}</li>
        <li>{t("processSubscriptionsPreventFraud")}</li>
        <li>{t("sendTransactionalEmailAccount")}</li>
        <li>{t("respondSupportRequests")}</li>
        <li>{t("detectAbuseEnforceOur")}</li>
      </ul>

      <h2>{t("n3AiProcessing")}</h2>
      <p>{t("whenYouUseAi")}</p>
      <p>
        <strong>{t("weDonAposT2")}</strong>
      </p>

      <h2>{t("n4DataSharing")}</h2>
      <p>{t("weShareDataOnly")}</p>
      <ul>
        <li>
          <strong>{t("subProcessors")}</strong>
          {t("weUseOperateService")}
        </li>
        <li>
          <strong>{t("authorities")}</strong>
          {t("ifRequiredByLaw")}
        </li>
        <li>
          <strong>{t("acquirer")}</strong>
          {t("eventMergerSaleWith")}
        </li>
      </ul>

      <h2>{t("n5Retention")}</h2>
      <p>{t("weKeepCustomerData")}</p>

      <h2>{t("n6YourRights")}</h2>
      <p>
        {t.rich("yourRightsDescription", {
          mail: (chunks) => <a href="mailto:privacy@example.com">{chunks}</a>,
        })}
      </p>

      <h2>{t("n7InternationalTransfers")}</h2>
      <p>{t("weHostPrimarilyEu")}</p>

      <h2>{t("n8Security")}</h2>
      <p>{t("weUseTlsTransit")}</p>

      <h2>{t("n9Children")}</h2>
      <p>{t("serviceIsnAposT")}</p>

      <h2>{t("n10Changes")}</h2>
      <p>{t("weAposLlNotify")}</p>

      <h2>{t("n11Contact")}</h2>
      <p>
        {t("questionsRequests")} <a href="mailto:privacy@example.com">{t("privacyExampleCom4")}</a>.
      </p>
    </>
  );
}
