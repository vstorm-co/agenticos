"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Skeleton, Spinner } from "@/components/ui";
import type { ChatModelLibraryProps } from "@/components/chat/chat-model-library";
import { StartModelCatalog } from "./start-model-catalog";
import styles from "./start-models.module.css";

/** The picker owns credentials and mutations; setup owns only which question is visible. */
export function StartProviderSetup(props: ChatModelLibraryProps) {
  const t = useTranslations("start.modelSetup");
  const common = useTranslations("common");
  const [editing, setEditing] = useState(false);
  const ready = !props.disabled && !props.loadingProviders && !props.needsCredential;
  const showModel = ready && !editing && !props.configurationForm;
  const section = useRef<HTMLElement>(null);
  function changeConnection(edit: boolean) {
    setEditing(edit);
    const viewport = section.current?.closest<HTMLElement>("[data-start-content]");
    if (viewport) viewport.scrollTop = 0;
  }
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [showModel]);
  return (
    <section ref={section} className={styles.stage}>
      <h3 ref={heading} tabIndex={-1} className={showModel ? "sr-only" : styles.stageTitle}>
        {t(showModel ? "modelTitle" : "connectionTitle")}
      </h3>
      {!showModel ? (
        <div className={styles.connection}>
          {props.disabled ? (
            props.failure ? null : (
              <div role="status" aria-label={common("loading")}>
                <Skeleton className="h-14 rounded-lg" />
              </div>
            )
          ) : (
            props.configurationForm || (
              <>
                {props.connectionLabel && (
                  <p className={styles.connected}>
                    <Check className="size-4" aria-hidden />
                    <span>{t("vaultKey", { name: props.connectionLabel })}</span>
                  </p>
                )}
                {props.credentialPicker}
                {props.credentialForm && (
                  <div className={styles.keyForm}>
                    <KeyRound aria-hidden className="text-muted-foreground size-4" />
                    {props.credentialForm}
                  </div>
                )}
                {ready && (
                  <Button
                    type="button"
                    className={styles.next}
                    onClick={() => changeConnection(false)}
                  >
                    {t("chooseModel")}
                    <ArrowRight aria-hidden className="size-4" />
                  </Button>
                )}
              </>
            )
          )}
        </div>
      ) : (
        <>
          {(props.connectionLabel || props.credentialPicker || props.credentialForm) && (
            <div className={styles.accountSummary}>
              <span className={styles.selectedAccount}>
                <Check className="text-success size-4 shrink-0" aria-hidden />
                <span>{props.connectionLabel ?? t("connectionTitle")}</span>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => changeConnection(true)}
              >
                {t("changeConnection")}
              </Button>
            </div>
          )}
          <StartModelCatalog {...props} />
        </>
      )}
      {props.failure}
      {props.applying && (
        <p role="status" className={styles.hint}>
          <Spinner className="size-4" />
          {t("applying")}
        </p>
      )}
    </section>
  );
}
