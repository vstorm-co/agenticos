import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OnboardingSetup } from "./onboarding-setup";

vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "AgenticOS", logoUrl: null }),
}));
vi.mock("@/components/layout/auth-guard", () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
import enMessages from "../../../messages/en.json";

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

afterEach(() => vi.restoreAllMocks());

describe("OnboardingSetup", () => {
  it("renders the guided team builder inside an auth guard", () => {
    render(<OnboardingSetup />);
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
    expect(screen.getByText("About you & your work")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /skip for now/i })).toBeInTheDocument();
  });
});
