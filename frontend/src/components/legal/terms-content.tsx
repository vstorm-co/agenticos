/**
 * Body of /legal/terms. Rendered as JSX (not one JSON message) because legal
 * text is paragraph/list/inline-link heavy and would be unwieldy as ICU strings.
 */
import { useTranslations } from "next-intl";

/** The deployment's name, resolved by the page above and interpolated into the text. */
interface LegalBodyProps {
  appName: string;
}

export function TermsBodyEn({ appName }: LegalBodyProps) {
  const t = useTranslations("legal");
  return (
    <>
      <p>{t("termsIntro", { appName })}</p>
      <p>{t("ifYouAposRe")}</p>

      <h2>{t("n1Service")}</h2>
      <p>{t("serviceDescription", { appName })}</p>

      <h2>{t("n2YourAccount")}</h2>
      <p>
        {t.rich("accountResponsibility", {
          mail: (chunks) => <a href="mailto:security@example.com">{chunks}</a>,
        })}
      </p>

      <h2>{t("n3AcceptableUse")}</h2>
      <p>{t("youWonAposT")}</p>
      <ul>
        <li>{t("breakLawViolateSomeone")}</li>
        <li>{t("generateContentIllegalHarmful")}</li>
        <li>{t("probeScanTestVulnerability")}</li>
        <li>{t("reverseEngineerServiceCompete")}</li>
        <li>{t("interfereWithOtherCustomers")}</li>
      </ul>

      <h2>{t("n4YourContent")}</h2>
      <p>{t("youOwnWhatYou")}</p>
      {/* One message with a tag, not a head and a tail. Split in two it rendered
          `...Customer Data.Period.` with no space in every language, and gave a
          translator half a sentence to work with. */}
      <p>{t.rich("weDoNotTrainOnCustomerData", { b: (chunks) => <strong>{chunks}</strong> })}</p>

      <h2>{t("n5SubscriptionsBilling")}</h2>
      <p>{t("paidPlansRenewAutomatically")}</p>
      <p>{t("creditsExpireAtEnd")}</p>

      <h2>{t("n6ThirdPartyServices")}</h2>
      <p>{t("serviceReliesThirdParty")}</p>

      <h2>{t("n7IntellectualProperty")}</h2>
      <p>{t("weRetainAllRights")}</p>

      <h2>{t("n8Termination")}</h2>
      <p>{t("youCanStopUsing")}</p>

      <h2>{t("n9Disclaimers")}</h2>
      <p>{t("serviceProvidedLdquoAs")}</p>
      <p>
        {t.rich("aiOutputDisclaimer", {
          strong: (chunks) => <strong>{chunks}</strong>,
        })}
      </p>

      <h2>{t("n10LimitationLiability")}</h2>
      <p>{t("extentPermittedByLaw")}</p>

      <h2>{t("n11ChangesTheseTerms")}</h2>
      <p>{t("weMayUpdateThese")}</p>

      <h2>{t("n12GoverningLaw")}</h2>
      <p>{t("theseTermsAreGoverned")}</p>

      <h2>{t("n13Contact")}</h2>
      <p>
        {t.rich("contactQuestions", {
          mail: (chunks) => <a href="mailto:legal@example.com">{chunks}</a>,
        })}
      </p>
    </>
  );
}
