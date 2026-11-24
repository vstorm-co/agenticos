"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { useBranding } from "@/components/branding/branding-provider";
import { Button } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { createOnboardingTeam, fetchTeamProposal } from "@/lib/onboarding/team-api";
import { useAuthStore } from "@/stores";
import type { User } from "@/types/auth";
import type {
  OnboardingTeamProposal,
  OnboardingTeamResult,
  ProposedSpecialist,
} from "@/types/onboarding";

import { StepAbout } from "./step-about";
import { StepDeploying } from "./step-deploying";
import { StepGoals } from "./step-goals";
import { StepTeam } from "./step-team";
import { StepTools } from "./step-tools";

export function TeamBuilder() {
  const t = useTranslations("onboardingTeam");
  const tErrors = useTranslations("errors");
  const { appName } = useBranding();
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);

  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);
  const [role, setRole] = useState("engineering");
  const [industry, setIndustry] = useState("software");
  const [teamSize, setTeamSize] = useState("small");
  const [goals, setGoals] = useState<string[]>(["releases", "support"]);
  const [details, setDetails] = useState("");
  const [tools, setTools] = useState<string[]>(["github", "slack"]);

  const [proposal, setProposal] = useState<OnboardingTeamProposal | null>(null);
  const [isLoadingProposal, setIsLoadingProposal] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<OnboardingTeamResult | null>(null);
  const [deployError, setDeployError] = useState<string | null>(null);

  const handleSkip = async () => {
    try {
      if (user && !user.onboarding_completed_at) {
        const updated = await apiClient.patch<User>("/users/me", {
          onboarding_completed_at: new Date().toISOString(),
        });
        if (updated) setUser(updated);
      }
    } catch {
      // non-blocking
    }
    router.push(ROUTES.CHAT);
  };

  const handleNext = async () => {
    if (step === 1) {
      setStep(2);
    } else if (step === 2) {
      setStep(3);
    } else if (step === 3) {
      setIsLoadingProposal(true);
      try {
        const data = await fetchTeamProposal({
          role,
          industry,
          team_size: teamSize,
          goals,
          details,
          tools,
        });
        setProposal(data);
        setStep(4);
      } catch {
        toast.error(t("generatingProposal"));
        // Fallback local proposal if backend unreachable
        setProposal({
          industry,
          role,
          rationale: "",
          lead: {
            name: "Team Orchestrator", // i18n-exempt: fallback preset
            role: "Coordinator", // i18n-exempt: fallback preset
            description: "Directs incoming requests and coordinates your specialist agents.", // i18n-exempt: fallback preset
            starters: [
              "Summarize our current priorities", // i18n-exempt: fallback preset
              "Help research and draft an update", // i18n-exempt: fallback preset
              "Coordinate tasks across specialists", // i18n-exempt: fallback preset
            ],
          },
          specialists: [
            {
              key: "general/agenticos",
              name: "General Assistant", // i18n-exempt: fallback preset
              role: "Research & Tasks", // i18n-exempt: fallback preset
              description: "Researches questions, writes documents, and answers questions.", // i18n-exempt: fallback preset
              capabilities: ["web_research", "artifacts"],
              recommended: true,
            },
            {
              key: "general/platform-assistant",
              name: "Platform Architect", // i18n-exempt: fallback preset
              role: "Builder", // i18n-exempt: fallback preset
              description: "Designs, tests, and tunes workflows and agents.", // i18n-exempt: fallback preset
              capabilities: ["skills", "artifacts"],
              recommended: true,
            },
          ],
        });
        setStep(4);
      } finally {
        setIsLoadingProposal(false);
      }
    }
  };

  const handleBack = () => {
    setStep((prev) => (prev === 4 ? 3 : prev === 3 ? 2 : prev === 2 ? 1 : prev));
  };

  const handleDeploy = async () => {
    if (!proposal) return;
    setIsDeploying(true);
    setDeployError(null);
    setStep(5);

    try {
      const result = await createOnboardingTeam({
        lead: proposal.lead,
        specialists: proposal.specialists,
      });
      setDeployResult(result);
      if (user) {
        setUser({
          ...user,
          onboarding_completed_at: new Date().toISOString(),
        });
      }
    } catch (err: unknown) {
      setDeployError(getErrorMessage(err, tErrors));
    } finally {
      setIsDeploying(false);
    }
  };

  const handleUpdateLeadName = (name: string) => {
    if (!proposal) return;
    setProposal({
      ...proposal,
      lead: { ...proposal.lead, name },
    });
  };

  const handleRemoveSpecialist = (idx: number) => {
    if (!proposal) return;
    setProposal({
      ...proposal,
      specialists: proposal.specialists.filter((_, i) => i !== idx),
    });
  };

  const handleAddSpecialist = (specialist: ProposedSpecialist) => {
    if (!proposal) return;
    setProposal({
      ...proposal,
      specialists: [...proposal.specialists, specialist],
    });
  };

  return (
    <div className="bg-background text-foreground flex min-h-screen flex-col">
      {/* Header */}
      <header className="border-border bg-background/80 sticky top-0 z-10 border-b backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-6 py-4">
          <span className="inline-flex items-center gap-2 text-base font-semibold tracking-tight">
            <span aria-hidden className="bg-brand inline-block h-2.5 w-2.5 rounded-full" />
            {appName}
          </span>

          <div className="flex items-center gap-4">
            {step < 5 && (
              <button
                type="button"
                onClick={handleSkip}
                className="text-muted-foreground hover:text-foreground text-xs font-medium transition-colors"
              >
                {t("skip")}
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-6 py-10"
      >
        {/* Progress Stepper Bar (steps 1 to 4) */}
        {step < 5 && (
          <div className="mb-8 space-y-2">
            <div className="text-muted-foreground flex items-center justify-between text-xs">
              <span className="font-medium">{t("stepTracker", { step })}</span>
              <span>
                {step === 1
                  ? t("stepProfile")
                  : step === 2
                    ? t("stepGoals")
                    : step === 3
                      ? t("stepTools")
                      : t("stepTeam")}
              </span>
            </div>
            <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
              <div
                className="bg-brand h-full transition-all duration-300"
                style={{ width: `${(step / 4) * 100}%` }}
              />
            </div>
          </div>
        )}

        {/* Step Views */}
        <div className="min-h-[380px]">
          {step === 1 && (
            <StepAbout
              role={role}
              industry={industry}
              teamSize={teamSize}
              onChange={(f) => {
                if (f.role !== undefined) setRole(f.role);
                if (f.industry !== undefined) setIndustry(f.industry);
                if (f.teamSize !== undefined) setTeamSize(f.teamSize);
              }}
            />
          )}

          {step === 2 && (
            <StepGoals
              goals={goals}
              details={details}
              onChange={(f) => {
                if (f.goals !== undefined) setGoals(f.goals);
                if (f.details !== undefined) setDetails(f.details);
              }}
            />
          )}

          {step === 3 && <StepTools tools={tools} onChange={setTools} />}

          {step === 4 && proposal && (
            <StepTeam
              proposal={proposal}
              onUpdateLeadName={handleUpdateLeadName}
              onRemoveSpecialist={handleRemoveSpecialist}
              onAddSpecialist={handleAddSpecialist}
              onDeploy={handleDeploy}
              isDeploying={isDeploying}
            />
          )}

          {step === 5 && (
            <StepDeploying
              isDeploying={isDeploying}
              result={deployResult}
              error={deployError}
              onRetry={handleDeploy}
            />
          )}
        </div>

        {/* Bottom Navigation (steps 1 - 3) */}
        {step >= 1 && step <= 3 && (
          <footer className="border-border mt-10 flex items-center justify-between border-t pt-6">
            {step > 1 ? (
              <Button type="button" variant="outline" onClick={handleBack} className="gap-2">
                <ArrowLeft className="size-4" />
                {t("back")}
              </Button>
            ) : (
              <div />
            )}

            <Button
              type="button"
              onClick={handleNext}
              disabled={isLoadingProposal}
              className="gap-2 px-6"
            >
              {isLoadingProposal ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  {t("generating")}
                </>
              ) : (
                <>
                  {t("continue")}
                  <ArrowRight className="size-4" />
                </>
              )}
            </Button>
          </footer>
        )}
      </main>
    </div>
  );
}
