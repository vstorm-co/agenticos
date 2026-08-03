/**
 * Body of /legal/terms in EN + PL. Both rendered as JSX (not JSON messages)
 * because legal text is paragraph/list/inline-link heavy and would be unwieldy
 * to translate via ICU strings.
 *
 * Switch by locale at the page level. To add another locale, add a new export
 * here with the same shape and update the dispatch in the page.
 */
import { APP_NAME } from "@/lib/constants";
import { useTranslations } from "next-intl";

export function TermsBodyEn() {
  const t = useTranslations("legal");
  return (
    <>
      <p>
        These Terms of Service (&ldquo;Terms&rdquo;) govern your access to and use of {APP_NAME}{" "}
        (the &ldquo;Service&rdquo;). By creating an account, accessing the Service, or clicking
        &ldquo;I agree,&rdquo; you accept these Terms.
      </p>
      <p>{t("ifYouAposRe")}</p>

      <h2>{t("n1Service")}</h2>
      <p>
        {APP_NAME} provides AI-assisted productivity software, including chat agents, retrieval
        augmented generation (RAG), and related developer tools. Features evolve continuously; we
        may add, change, or remove functionality.
      </p>

      <h2>{t("n2YourAccount")}</h2>
      <p>
        You&apos;re responsible for keeping your credentials secure and for activity that happens
        under your account. Notify us at{" "}
        <a href="mailto:security@example.com">{t("securityExampleCom")}</a>
        {t("ifYouSuspectCompromise")}
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
        AI output may contain inaccuracies. <strong>{t("donAposTRely")}</strong>
        {t("medicalLegalFinancialWithout")}
      </p>

      <h2>{t("n10LimitationLiability")}</h2>
      <p>{t("extentPermittedByLaw")}</p>

      <h2>{t("n11ChangesTheseTerms")}</h2>
      <p>{t("weMayUpdateThese")}</p>

      <h2>{t("n12GoverningLaw")}</h2>
      <p>{t("theseTermsAreGoverned")}</p>

      <h2>{t("n13Contact")}</h2>
      <p>
        Questions? Email <a href="mailto:legal@example.com">{t("legalExampleCom")}</a>
        {t("weRespondWithinFive")}
      </p>
    </>
  );
}

export function TermsBodyPl() {
  const t = useTranslations("legal");
  return (
    <>
      <p>
        Niniejszy Regulamin (&bdquo;Regulamin&rdquo;) określa zasady dostępu i korzystania z{" "}
        {APP_NAME} (&bdquo;Usługa&rdquo;). Zakładając konto, uzyskując dostęp do Usługi lub klikając
        &bdquo;Zgadzam się&rdquo;, akceptujesz ten Regulamin.
      </p>
      <p>{t("jeLiKorzystaszZ")}</p>

      <h2>{t("n1UsUga")}</h2>
      <p>
        {APP_NAME} dostarcza oprogramowanie produktywności wspomagane AI - agentów do chatu,
        retrieval augmented generation (RAG) oraz powiązane narzędzia developerskie. Funkcje
        ewoluują na bieżąco; możemy je dodawać, zmieniać lub usuwać.
      </p>

      <h2>{t("n2TwojeKonto")}</h2>
      <p>
        Odpowiadasz za bezpieczeństwo swoich danych logowania oraz za działania wykonane na Twoim
        koncie. Powiadom nas na <a href="mailto:security@example.com">{t("securityExampleCom2")}</a>
        {t("jeLiPodejrzewaszE")}
      </p>

      <h2>{t("n3AkceptowalneUYcie")}</h2>
      <p>{t("nieBDzieszKorzysta")}</p>
      <ul>
        <li>łamać prawo lub naruszać praw osób trzecich;</li>
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
        Output AI może zawierać nieścisłości. <strong>{t("niePolegajNaUs")}</strong>
        {t("medycznePrawneFinansoweBez")}
      </p>

      <h2>{t("n10OgraniczenieOdpowiedzialnoCi")}</h2>
      <p>{t("wZakresieDozwolonymPrawem")}</p>

      <h2>{t("n11ZmianyRegulaminu")}</h2>
      <p>{t("moEmyAktualizowaTen")}</p>

      <h2>{t("n12PrawoWCiwe")}</h2>
      <p>{t("niniejszyRegulaminPodlegaPrawu")}</p>

      <h2>{t("n13Kontakt")}</h2>
      <p>
        Pytania? Napisz na <a href="mailto:legal@example.com">{t("legalExampleCom2")}</a>
        {t("odpowiadamyWCiGu")}
      </p>
    </>
  );
}
