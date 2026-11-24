import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TeamBuilder } from "./team-builder";
import * as teamApi from "@/lib/onboarding/team-api";
import { ROUTES } from "@/lib/constants";
import { ApiError } from "@/lib/api-error";

vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "AgenticOS", logoUrl: null }),
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import enMessages from "../../../../messages/en.json";

vi.mock("next-intl", () => ({
  useTranslations: (namespace?: string) => {
    const section: unknown = namespace
      ? (enMessages as unknown as Record<string, unknown>)[namespace]
      : enMessages;
    return (key: string, params?: Record<string, unknown>) => {
      let value: unknown = section;
      for (const part of key.split(".")) {
        if (typeof value !== "object" || value === null || !(part in value)) {
          value = undefined;
          break;
        }
        value = (value as Record<string, unknown>)[part];
      }
      if (typeof value !== "string") return key;
      if (!params) return value;
      return Object.entries(params).reduce(
        (result, [name, replacement]) =>
          result.replace(new RegExp(`\\{${name}\\}`, "g"), String(replacement)),
        value,
      );
    };
  },
}));

describe("TeamBuilder", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("guides the user step by step to build a recommended team of agents", async () => {
    vi.spyOn(teamApi, "fetchTeamProposal").mockResolvedValue({
      industry: "software",
      role: "Engineering / Developer",
      rationale: "Tailored team for engineering speed.",
      lead: {
        name: "Tech Lead",
        role: "Engineering Coordinator",
        description: "Coordinates specialists and reviews work.",
        starters: ["Draft release notes"],
      },
      specialists: [
        {
          key: "software/api-support",
          name: "API Support",
          role: "Integrations",
          description: "Answers integration questions.",
          capabilities: ["web_research"],
          recommended: true,
        },
        {
          key: "software/release-writer",
          name: "Release Notes Writer",
          role: "Releases",
          description: "Writes release notes.",
          capabilities: ["artifacts"],
          recommended: true,
        },
      ],
    });

    vi.spyOn(teamApi, "createOnboardingTeam").mockResolvedValue({
      lead_agent_id: "lead-123",
      lead_agent_slug: "tech-lead",
      lead_conversation_id: "conv-123",
      created_agents: [
        {
          id: "lead-123",
          name: "Tech Lead",
          slug: "tech-lead",
          role: "Engineering Coordinator",
          is_lead: true,
          status: "published",
        },
        {
          id: "spec-1",
          name: "API Support",
          slug: "api-support",
          role: "Integrations",
          is_lead: false,
          status: "published",
        },
      ],
      message: "Team ready",
    });

    render(<TeamBuilder />);

    // Step 1: About
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
    expect(screen.getByText("About you & your work")).toBeInTheDocument();
    expect(screen.getByText("Engineering / Tech")).toBeInTheDocument();
    expect(screen.getByText("Software & Technology")).toBeInTheDocument();

    // Advance to Step 2: Goals
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByText("Step 2 of 4")).toBeInTheDocument();
    expect(screen.getByText("What should your AI team handle?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    // Advance to Step 3: Tools
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByText("Step 3 of 4")).toBeInTheDocument();
    expect(screen.getByText("Tools & integrations")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByText("Step 2 of 4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByRole("link", { name: /connect apps/i })).toHaveAttribute(
      "href",
      ROUTES.CONNECTORS,
    );

    // Back is offered while choosing tools. Re-enter that step before generating the team.
    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByText("Step 2 of 4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByText("Step 3 of 4")).toBeInTheDocument();

    // Advance to Step 4: Recommended Team
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(screen.getByText("Step 4 of 4")).toBeInTheDocument();
      expect(screen.getByText("Your recommended AI team")).toBeInTheDocument();
    });

    expect(screen.getByDisplayValue("Tech Lead")).toBeInTheDocument();
    expect(screen.getByText("API Support")).toBeInTheDocument();
    expect(screen.getByText("Release Notes Writer")).toBeInTheDocument();
    await screen.findByText("Your recommended AI team");

    // Deploy Team
    fireEvent.click(screen.getByRole("button", { name: /build & deploy my team/i }));

    await waitFor(() => {
      expect(screen.getByText("Your AI team is ready!")).toBeInTheDocument();
    });

    expect(screen.getByRole("link", { name: /chat with your team lead/i })).toHaveAttribute(
      "href",
      `${ROUTES.CHAT}?id=conv-123`,
    );
  });

  it("allows user to skip to workspace at any point", async () => {
    render(<TeamBuilder />);
    const skipButton = screen.getByRole("button", { name: /skip for now/i });
    fireEvent.click(skipButton);
    expect(mockPush).toHaveBeenCalledWith(ROUTES.CHAT);
  });

  it.each([
    [
      new ApiError(500, "Untranslated proxy failure", { code: "INTERNAL_SERVER_ERROR" }),
      enMessages.errors.internalServerError,
    ],
    [{ reason: "not an Error" }, enMessages.errors.unexpected],
  ] as const)(
    "renders a deployment failure through the localized error contract",
    async (failure, message) => {
      vi.spyOn(teamApi, "fetchTeamProposal").mockResolvedValue({
        industry: "software",
        role: "engineering",
        rationale: "A small team",
        lead: {
          name: "Team lead",
          role: "Coordinator",
          description: "Coordinates work",
          starters: [],
        },
        specialists: [
          {
            key: "software/api-support",
            name: "API Support",
            role: "Integrations",
            description: "Answers integration questions.",
            capabilities: ["web_research"],
            recommended: true,
          },
        ],
      });
      vi.spyOn(teamApi, "createOnboardingTeam").mockRejectedValue(failure);
      render(<TeamBuilder />);
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
      fireEvent.click(screen.getByRole("button", { name: /continue/i }));
      await screen.findByText("Your recommended AI team");
      expect(screen.getByRole("button", { name: /build & deploy my team/i })).toBeEnabled();
      fireEvent.click(screen.getByRole("button", { name: /build & deploy my team/i }));

      expect(await screen.findByText(message)).toBeVisible();
      expect(teamApi.createOnboardingTeam).toHaveBeenCalledOnce();
      expect(screen.queryByText("Untranslated proxy failure")).toBeNull();
      expect(screen.queryByText("Your AI team is ready!")).toBeNull();
    },
  );
});
