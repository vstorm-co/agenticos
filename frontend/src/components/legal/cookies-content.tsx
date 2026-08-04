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
        Questions: <a href="mailto:privacy@example.com">{t("privacyExampleCom")}</a>.
      </p>
    </>
  );
}

export function CookiesBodyPl() {
  const t = useTranslations("legal.pl");
  return (
    <>
      <p>{t("uYwamyPlikW")}</p>

      <h2>{t("czymJestPlikCookie")}</h2>
      <p>{t("maYPlikKt")}</p>

      <h2>{t("kategorie")}</h2>
      <h3>{t("niezbDne")}</h3>
      <p>{t("wymaganeDoDziaAnia")}</p>
      <ul>
        <li>
          <code>{t("authSession2")}</code>
          {t("twojaUwierzytelnionaSesjaHttponly")}
        </li>
        <li>
          <code>{t("theme2")}</code>
          {t("preferencjaJasnyCiemny")}
        </li>
        <li>
          <code>{t("locale2")}</code>
          {t("wybranyJZyk")}
        </li>
      </ul>

      <h3>{t("analityczne")}</h3>
      <p>{t("pomagajNamZrozumieJak")}</p>
      <ul>
        <li>
          <code>{t("analyticsSession2")}</code>
          {t("licznikWyWietleI")}
        </li>
      </ul>

      <h3>{t("funkcjonalne")}</h3>
      <p>{t("pamiTajTwojeWybory")}</p>
      <ul>
        <li>
          <code>{t("cookieConsent2")}</code>
          {t("twojaOdpowiedNaBanner")}
        </li>
      </ul>

      <h2>{t("twojeWybory")}</h2>
      <p>{t("moEszZaakceptowaOdrzuci")}</p>
      <p>{t("moEszTeBlokowa")}</p>

      <h2>{t("cookiesStronTrzecich")}</h2>
      <p>{t("nieUstawiamyReklamowychCookies")}</p>

      <h2>{t("kontakt")}</h2>
      <p>
        Pytania: <a href="mailto:privacy@example.com">{t("privacyExampleCom2")}</a>.
      </p>
    </>
  );
}
