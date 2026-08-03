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

      <h2>1. The Service</h2>
      <p>
        {APP_NAME} provides AI-assisted productivity software, including chat agents, retrieval
        augmented generation (RAG), and related developer tools. Features evolve continuously; we
        may add, change, or remove functionality.
      </p>

      <h2>2. Your account</h2>
      <p>
        You&apos;re responsible for keeping your credentials secure and for activity that happens
        under your account. Notify us at{" "}
        <a href="mailto:security@example.com">{t("securityExampleCom")}</a>
        {t("ifYouSuspectCompromise")}
      </p>

      <h2>3. Acceptable use</h2>
      <p>{t("youWonAposT")}</p>
      <ul>
        <li>{t("breakLawViolateSomeone")}</li>
        <li>{t("generateContentIllegalHarmful")}</li>
        <li>{t("probeScanTestVulnerability")}</li>
        <li>{t("reverseEngineerServiceCompete")}</li>
        <li>{t("interfereWithOtherCustomers")}</li>
      </ul>

      <h2>4. Your content</h2>
      <p>{t("youOwnWhatYou")}</p>
      <p>
        <strong>{t("weDonAposT3")}</strong>
        {t("period")}
      </p>

      <h2>5. Subscriptions and billing</h2>
      <p>{t("paidPlansRenewAutomatically")}</p>
      <p>{t("creditsExpireAtEnd")}</p>

      <h2>6. Third-party services</h2>
      <p>{t("serviceReliesThirdParty")}</p>

      <h2>7. Intellectual property</h2>
      <p>{t("weRetainAllRights")}</p>

      <h2>8. Termination</h2>
      <p>{t("youCanStopUsing")}</p>

      <h2>9. Disclaimers</h2>
      <p>{t("serviceProvidedLdquoAs")}</p>
      <p>
        AI output may contain inaccuracies. <strong>{t("donAposTRely")}</strong> (medical, legal,
        financial) without independent verification.
      </p>

      <h2>10. Limitation of liability</h2>
      <p>{t("extentPermittedByLaw")}</p>

      <h2>11. Changes to these Terms</h2>
      <p>{t("weMayUpdateThese")}</p>

      <h2>12. Governing law</h2>
      <p>{t("theseTermsAreGoverned")}</p>

      <h2>13. Contact</h2>
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

      <h2>1. Usługa</h2>
      <p>
        {APP_NAME} dostarcza oprogramowanie produktywności wspomagane AI - agentów do chatu,
        retrieval augmented generation (RAG) oraz powiązane narzędzia developerskie. Funkcje
        ewoluują na bieżąco; możemy je dodawać, zmieniać lub usuwać.
      </p>

      <h2>2. Twoje konto</h2>
      <p>
        Odpowiadasz za bezpieczeństwo swoich danych logowania oraz za działania wykonane na Twoim
        koncie. Powiadom nas na <a href="mailto:security@example.com">{t("securityExampleCom2")}</a>
        {t("jeLiPodejrzewaszE")}
      </p>

      <h2>3. Akceptowalne użycie</h2>
      <p>{t("nieBDzieszKorzysta")}</p>
      <ul>
        <li>łamać prawo lub naruszać praw osób trzecich;</li>
        <li>{t("generowaTreCiNielegalnych")}</li>
        <li>{t("sondowaSkanowaLubTestowa")}</li>
        <li>{t("reverseEngineerowaUsUgi")}</li>
        <li>{t("zakCaKorzystaniaZ")}</li>
      </ul>

      <h2>4. Twoje treści</h2>
      <p>{t("jesteWCicielemTego")}</p>
      <p>
        <strong>{t("nieTrenujemyNaTwoich")}</strong>
        {t("kropka")}
      </p>

      <h2>5. Subskrypcje i płatności</h2>
      <p>{t("planyPAtneOdnawiaj")}</p>
      <p>{t("kredytyWygasajNaKo")}</p>

      <h2>6. Usługi stron trzecich</h2>
      <p>{t("usUgaPolegaNa")}</p>

      <h2>7. Własność intelektualna</h2>
      <p>{t("zachowujemyWszystkiePrawaDo")}</p>

      <h2>8. Wypowiedzenie</h2>
      <p>{t("moEszPrzestaKorzysta")}</p>

      <h2>9. Wyłączenia odpowiedzialności</h2>
      <p>{t("usUgaJestDostarczana")}</p>
      <p>
        Output AI może zawierać nieścisłości. <strong>{t("niePolegajNaUs")}</strong> (medyczne,
        prawne, finansowe) bez niezależnej weryfikacji.
      </p>

      <h2>10. Ograniczenie odpowiedzialności</h2>
      <p>{t("wZakresieDozwolonymPrawem")}</p>

      <h2>11. Zmiany Regulaminu</h2>
      <p>{t("moEmyAktualizowaTen")}</p>

      <h2>12. Prawo właściwe</h2>
      <p>{t("niniejszyRegulaminPodlegaPrawu")}</p>

      <h2>13. Kontakt</h2>
      <p>
        Pytania? Napisz na <a href="mailto:legal@example.com">{t("legalExampleCom2")}</a>
        {t("odpowiadamyWCiGu")}
      </p>
    </>
  );
}
