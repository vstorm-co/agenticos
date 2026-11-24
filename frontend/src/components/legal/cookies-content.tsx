import { useTranslations } from "next-intl";

export function CookiesBodyEn() {
  const t = useTranslations("legal");
  return (
    <>
      <p>{t("weUseCookiesSimilar")}</p>

      <h2>{t("whatCookie")}</h2>
      <p>{t("smallFileYourBrowser")}</p>

      <h2>{t("categories")}</h2>
      <h3>{t("essential2")}</h3>
      <p>{t("requiredServiceWorkThese")}</p>
      <ul>
        <li>
          <code>{t("authSession")}</code>
          {t("yourAuthenticatedSessionHttponly")}
        </li>
        <li>
          <code>{t("theme")}</code>
          {t("lightDarkPreference")}
        </li>
        <li>
          <code>{t("locale")}</code>
          {t("yourSelectedLanguage")}
        </li>
      </ul>

      <h3>{t("analytics2")}</h3>
      <p>{t("helpUsUnderstandHow")}</p>
      <ul>
        <li>
          <code>{t("analyticsSession")}</code>
          {t("pageviewFeatureUsageCounters")}
        </li>
      </ul>

      <h3>{t("functional2")}</h3>
      <p>{t("rememberYourChoicesMake")}</p>
      <ul>
        <li>
          <code>{t("cookieConsent")}</code>
          {t("yourResponseCookieBanner")}
        </li>
      </ul>

      <h2>{t("yourChoices")}</h2>
      <p>{t("youCanAcceptReject")}</p>
      <p>{t("youCanAlsoBlock")}</p>

      <h2>{t("thirdPartyCookies")}</h2>
      <p>{t("weDonAposT")}</p>

      <h2>{t("contact")}</h2>
      <p>
        {t("questions")} <a href="mailto:privacy@example.com">{t("privacyExampleCom")}</a>.
      </p>
    </>
  );
}
