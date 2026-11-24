"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight, CheckCircle2, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { OnboardingTeamResult } from "@/types/onboarding";

interface StepDeployingProps {
  isDeploying: boolean;
  result: OnboardingTeamResult | null;
  error: string | null;
  onRetry: () => void;
}

export function StepDeploying({ isDeploying, result, error, onRetry }: StepDeployingProps) {
  const t = useTranslations("onboardingTeam");
  const [activeStep, setActiveStep] = useState(1);

  useEffect(() => {
    if (!isDeploying || result) return;
    const timer = setInterval(() => {
      setActiveStep((prev) => (prev < 4 ? prev + 1 : prev));
    }, 1200);
    return () => clearInterval(timer);
  }, [isDeploying, result]);

  const steps = [
    t("deployingStep1"),
    t("deployingStep2"),
    t("deployingStep3"),
    t("deployingStep4"),
  ];

  if (error) {
    return (
      <div className="bg-card border-border flex flex-col items-center justify-center space-y-4 rounded-2xl border p-8 text-center">
        <div className="bg-destructive/10 text-destructive flex size-12 items-center justify-center rounded-full">
          !
        </div>
        <h3 className="text-foreground text-lg font-semibold">{t("errorTitle")}</h3>
        <p className="text-muted-foreground max-w-md text-sm">{error}</p>
        <Button onClick={onRetry} variant="outline" className="mt-2">
          {t("tryAgain")}
        </Button>
      </div>
    );
  }

  if (result) {
    const chatHref = result.lead_conversation_id
      ? `${ROUTES.CHAT}?id=${result.lead_conversation_id}`
      : ROUTES.CHAT;

    return (
      <div className="bg-card border-brand/30 flex flex-col items-center justify-center space-y-6 rounded-2xl border p-8 text-center shadow-sm">
        <div className="border-brand/20 bg-brand/10 text-brand flex size-14 items-center justify-center rounded-2xl">
          <Sparkles className="size-7" />
        </div>

        <div className="space-y-2">
          <h2 className="text-foreground text-2xl font-bold tracking-tight">{t("successTitle")}</h2>
          <p className="text-muted-foreground max-w-md text-sm leading-relaxed">
            {t("successSubtitle")}
          </p>
        </div>

        <div className="border-border/60 bg-muted/40 flex w-full max-w-md flex-col gap-2 rounded-xl border p-4 text-left">
          <div className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
            {t("teamMembersCreated")}
          </div>
          <div className="space-y-1.5">
            {result.created_agents.map((agent) => (
              <div key={agent.id} className="flex items-center justify-between text-xs">
                <span className="text-foreground font-medium">
                  {agent.name} {agent.is_lead && "(Lead)"}
                </span>
                <span className="text-muted-foreground text-[11px] capitalize">{agent.status}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row">
          <Button asChild size="lg" className="gap-2 px-6">
            <Link href={chatHref}>
              {t("startChat")}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link href={ROUTES.AGENTS}>{t("viewAgents")}</Link>
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card border-border flex flex-col items-center justify-center space-y-8 rounded-2xl border p-8 text-center shadow-sm sm:p-12">
      <div className="space-y-2">
        <h2 className="text-foreground text-xl font-semibold tracking-tight">
          {t("deployingTitle")}
        </h2>
        <p className="text-muted-foreground text-sm">{t("deployingSubtitle")}</p>
      </div>

      <div className="w-full max-w-sm space-y-3.5 text-left">
        {steps.map((label, idx) => {
          const stepNum = idx + 1;
          const isDone = activeStep > stepNum;
          const isCurrent = activeStep === stepNum;

          return (
            <div key={idx} className="flex items-center gap-3">
              {isDone ? (
                <CheckCircle2 className="text-brand size-5 shrink-0" />
              ) : isCurrent ? (
                <Loader2 className="text-brand size-5 shrink-0 animate-spin" />
              ) : (
                <div className="border-border size-5 shrink-0 rounded-full border" />
              )}
              <span
                className={`text-xs ${
                  isCurrent
                    ? "text-foreground font-medium"
                    : isDone
                      ? "text-muted-foreground"
                      : "text-muted-foreground/60"
                }`}
              >
                {label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
