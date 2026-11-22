"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ROUTES } from "@/lib/constants";
import { useTranslations } from "next-intl";
import { ArrowUpRight, MessageCircle, Wrench } from "lucide-react";
import { AvatarFace } from "@/components/ui/avatar-face";
import { Button } from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { useAgents } from "@/hooks/use-agents";
import { useAssistant } from "@/hooks/use-assistant";
import { useRouter } from "@/lib/locale-navigation";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { Onboarding } from "@/lib/onboarding-api";
import { StartSetup } from "./start-setup";
import styles from "./start-experience.module.css";

/** Launch real installed agents. Merely opening this step never sends a model request. */
export function StartLaunch({ data }: { data: Onboarding }) {
  const t = useTranslations("start.experience");
  const start = useTranslations("start");
  const [setupOpen, setSetupOpen] = useState(false);
  const setupButton = useRef<HTMLButtonElement>(null);
  const starterHeading = useRef<HTMLHeadingElement>(null);
  const agents = useAgents();
  const assistant = useAssistant();
  const router = useRouter();
  // Older published installations predate the provenance marker. Their canonical
  // slug identifies the card only; the server's runnable list still authorizes it.
  const starter =
    agents.agents.find((agent) => agent.is_starter) ??
    agents.agents.find((agent) => agent.slug === "agenticos" && agent.status === "published");
  const runnable = starter && data.agents.some((agent) => agent.id === starter.id);
  const setup = starter && data.setup_agent?.id === starter.id;
  const existingStarter = starter ?? agents.agents.find((agent) => agent.slug === "agenticos");
  return (
    <div className={styles.launch}>
      <div className={styles.agentCards}>
        <article className={styles.agentCard} data-start-launch-agent="agenticos">
          <span className={styles.agentFace}>
            <AvatarFace seed={starter?.slug ?? "agenticos"} />
          </span>
          <div>
            <span className={styles.eyebrow}>{t("dailyPartner")}</span>
            <h2 ref={starterHeading} tabIndex={-1}>
              {starter?.name ?? t("agenticosName")}
            </h2>
            <p>{t("agenticosBody")}</p>
          </div>
          {agents.isLoading ? (
            <LoadingState variant="pending" className="min-h-11 w-full justify-start" />
          ) : agents.error ? (
            <ErrorState
              title={t("agentsFailed")}
              cta={{ label: t("retry"), onClick: () => void agents.refetch() }}
            />
          ) : runnable || setup ? (
            <Link
              href={`/chat?with=${encodeURIComponent(starter.id)}`}
              className={styles.launchLink}
            >
              <MessageCircle size={16} aria-hidden />
              {t(setup ? "setupAgent" : "openAgent")}
              <ArrowUpRight size={16} aria-hidden />
            </Link>
          ) : (
            <div>
              <p className={styles.connectionFootnote}>{t("agentUnavailable")}</p>
              {existingStarter?.can_edit ? (
                <Link
                  className="mt-3 inline-flex text-sm underline underline-offset-4"
                  href={ROUTES.AGENT_DETAIL(existingStarter.id)}
                >
                  {t("configureAgent")}
                </Link>
              ) : !existingStarter && data.can_prepare ? (
                <Button
                  ref={setupButton}
                  className="mt-3"
                  variant="outline"
                  onClick={() => setSetupOpen(true)}
                >
                  {start("workbench.connect")}
                </Button>
              ) : null}
            </div>
          )}
        </article>
        <article className={styles.agentCard} data-start-launch-agent="architect">
          <span className={styles.agentFace}>
            <AvatarFace seed={assistant.assistant?.slug ?? "architect"} />
          </span>
          <div>
            <span className={styles.eyebrow}>{t("builderPartner")}</span>
            <h2>{assistant.assistant?.name ?? t("architectName")}</h2>
            <p>{t("architectBody")}</p>
          </div>
          {assistant.isLoading ? (
            <LoadingState variant="pending" className="min-h-11 w-full justify-start" />
          ) : assistant.error ? (
            <ErrorState
              title={t("agentsFailed")}
              cta={{ label: t("retry"), onClick: assistant.retry }}
            />
          ) : assistant.assistant?.can_use && assistant.assistant.status === "ready" ? (
            <Button
              variant="outline"
              onClick={() => {
                useArchitectAskStore.getState().open();
                router.push("/chat");
              }}
            >
              <Wrench size={16} aria-hidden />
              {t("openArchitect")}
            </Button>
          ) : (
            <div>
              <p className={styles.connectionFootnote}>{t("architectUnavailable")}</p>
              {assistant.assistant?.can_configure && assistant.assistant.agent_id && (
                <Link
                  className="mt-3 inline-flex text-sm underline underline-offset-4"
                  href={ROUTES.AGENT_DETAIL(assistant.assistant.agent_id)}
                >
                  {t("configureArchitect")}
                </Link>
              )}
            </div>
          )}
        </article>
      </div>
      {data.can_prepare && (
        <StartSetup
          data={data}
          open={setupOpen}
          onOpenChange={setSetupOpen}
          onReturnFocus={() => (setupButton.current ?? starterHeading.current)?.focus()}
        />
      )}
      <p className={styles.connectionFootnote}>{t("launchHint")}</p>
    </div>
  );
}
