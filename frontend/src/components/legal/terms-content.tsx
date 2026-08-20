/**
 * Body of /legal/terms in EN + PL. Both rendered as JSX (not JSON messages)
 * because legal text is paragraph/list/inline-link heavy and would be unwieldy
 * to translate via ICU strings.
 *
 * Switch by locale at the page level. To add another locale, add a new export
 * here with the same shape and update the dispatch in the page.
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
      <p>
        <strong>{t("weDonAposT3")}</strong>
        {t("period")}
      </p>

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

export function TermsBodyPl({ appName }: LegalBodyProps) {
  const t = useTranslations("legal.pl");
  return (
    <>
      <p>{t("termsIntro", { appName })}</p>
      <p>{t("jeLiKorzystaszZ")}</p>

      <h2>{t("n1UsUga")}</h2>
      <p>{t("serviceDescription", { appName })}</p>

      <h2>{t("n2TwojeKonto")}</h2>
      <p>
        {t.rich("accountResponsibility", {
          mail: (chunks) => <a href="mailto:security@example.com">{chunks}</a>,
        })}
      </p>

      <h2>{t("n3AkceptowalneUYcie")}</h2>
      <p>{t("nieBDzieszKorzysta")}</p>
      <ul>
        <li>{t("amaPrawoLubNarusza")}</li>
        <li>{t("generowaTreCiNielegalnych")}</li>
        <li>{t("sondowaSkanowaLubTestowa")}</li>
        <li>{t("reverseEngineerowaUsUgi")}</li>
        <li>{t("zakCaKorzystaniaZ")}</li>
      </ul>

      <h2>{t("n4TwojeTreCi")}</h2>
      <p>{t("jesteWCicielemTego")}</p>
      <p>
        <strong>{t("nieTrenujemyNaTwoich")}</strong>
        {t("kropka")}
      </p>

      <h2>{t("n5SubskrypcjeIP")}</h2>
      <p>{t("planyPAtneOdnawiaj")}</p>
      <p>{t("kredytyWygasajNaKo")}</p>

      <h2>{t("n6UsUgiStron")}</h2>
      <p>{t("usUgaPolegaNa")}</p>

      <h2>{t("n7WAsnoIntelektualna")}</h2>
      <p>{t("zachowujemyWszystkiePrawaDo")}</p>

      <h2>{t("n8Wypowiedzenie")}</h2>
      <p>{t("moEszPrzestaKorzysta")}</p>

      <h2>{t("n9WyCzeniaOdpowiedzialno")}</h2>
      <p>{t("usUgaJestDostarczana")}</p>
      <p>
        {t.rich("aiOutputDisclaimer", {
          strong: (chunks) => <strong>{chunks}</strong>,
        })}
      </p>

      <h2>{t("n10OgraniczenieOdpowiedzialnoCi")}</h2>
      <p>{t("wZakresieDozwolonymPrawem")}</p>

      <h2>{t("n11ZmianyRegulaminu")}</h2>
      <p>{t("moEmyAktualizowaTen")}</p>

      <h2>{t("n12PrawoWCiwe")}</h2>
      <p>{t("niniejszyRegulaminPodlegaPrawu")}</p>

      <h2>{t("n13Kontakt")}</h2>
      <p>
        {t.rich("contactQuestions", {
          mail: (chunks) => <a href="mailto:legal@example.com">{chunks}</a>,
        })}
      </p>
    </>
  );
}
