import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ImportSkillPackageDialog } from "./import-skill-package-dialog";
import {
  applySkillPackage,
  previewSkillPackage,
  type SkillPackagePreview,
} from "@/lib/skill-package-api";
const scope = vi.hoisted(() => ({ tenant: "org-a" }));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => scope.tenant,
  useTenantGuard: () => (start: string) => scope.tenant === start,
}));
vi.mock("@/lib/skill-package-api", () => ({
  previewSkillPackage: vi.fn(),
  applySkillPackage: vi.fn(),
}));
vi.mock("@/hooks", () => ({ useSkillResource: vi.fn() }));
const preview: SkillPackagePreview = {
  name: "template",
  description: "Prepare a proposal",
  content: "Do it",
  category: null,
  manifest_metadata: {},
  fingerprint: "digest",
  execution: "none",
  total_bytes: 90,
  max_file_bytes: 8388608,
  max_package_bytes: 33554432,
  max_files: 1024,
  files: [{ name: "assets/template.xlsx", size_bytes: 12, sha256: "hash", encoding: "base64" }],
};
function setup() {
  const imported = vi.fn();
  const close = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const rendered = render(
    <QueryClientProvider client={client}>
      <ImportSkillPackageDialog open onOpenChange={close} onImported={imported} />
    </QueryClientProvider>,
  );
  const input = () => rendered.container.ownerDocument.querySelector('input[type="file"]')!;
  return { ...rendered, imported, close, input, client };
}
beforeEach(() => {
  vi.clearAllMocks();
  scope.tenant = "org-a";
  vi.mocked(previewSkillPackage).mockResolvedValue(preview);
  vi.mocked(applySkillPackage).mockResolvedValue({
    skill_id: "new",
    version_id: "v1",
    name: "template",
    files: 1,
    fingerprint: "digest",
  });
});
it("previews paths and binary type before explicitly applying the exact reviewed files", async () => {
  const view = setup();
  const file = new File(["---"], "SKILL.md");
  expect(screen.getByRole("button", { name: "Import skill" })).toBeDisabled();
  fireEvent.change(view.input(), { target: { files: [file] } });
  await screen.findByText("assets/template.xlsx");
  expect(screen.getByText(/Import never runs scripts/)).toBeInTheDocument();
  expect(applySkillPackage).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Import skill" }));
  await waitFor(() => expect(view.imported).toHaveBeenCalledWith("new"));
  expect(applySkillPackage).toHaveBeenCalledWith([file], "directory", "digest");
});
it("shows refusal and never enables apply for an invalid package", async () => {
  vi.mocked(previewSkillPackage).mockRejectedValue(new Error("unsafe package"));
  const view = setup();
  fireEvent.change(view.input(), { target: { files: [new File(["bad"], "SKILL.md")] } });
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Import skill" })).toBeDisabled();
  expect(applySkillPackage).not.toHaveBeenCalled();
});
it("discards a preview response after the user changes organizations", async () => {
  let resolve!: (value: SkillPackagePreview) => void;
  vi.mocked(previewSkillPackage).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const view = setup();
  fireEvent.change(view.input(), { target: { files: [new File(["body"], "SKILL.md")] } });
  scope.tenant = "org-b";
  await act(async () => resolve(preview));
  expect(screen.queryByText("assets/template.xlsx")).not.toBeInTheDocument();
  expect(view.imported).not.toHaveBeenCalled();
});

it("previews a ZIP's text files and cancels without importing", async () => {
  vi.mocked(previewSkillPackage).mockResolvedValue({
    ...preview,
    files: [{ name: "guide.txt", encoding: "utf8", size_bytes: 12, sha256: "hash" }],
  });
  const view = setup();
  const inputs = view.container.ownerDocument.querySelectorAll('input[type="file"]');
  const file = new File(["archive"], "skill.zip");
  const zip = inputs[1];
  if (!zip) throw new Error("Expected the ZIP upload input");
  fireEvent.change(zip, { target: { files: [file] } });
  await screen.findByText("guide.txt");
  expect(previewSkillPackage).toHaveBeenCalledWith([file], "zip");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(view.close).toHaveBeenCalledWith(false);
  expect(applySkillPackage).not.toHaveBeenCalled();
});

it("allows escape when idle and keeps the package open while an apply is pending", async () => {
  const view = setup();
  await userEvent.keyboard("{Escape}");
  expect(view.close).toHaveBeenCalledWith(false);
  view.close.mockClear();
  let reject!: (error: Error) => void;
  vi.mocked(applySkillPackage).mockReturnValue(
    new Promise((_, fail) => {
      reject = fail;
    }),
  );
  fireEvent.change(view.input(), { target: { files: [new File(["body"], "SKILL.md")] } });
  await screen.findByText("assets/template.xlsx");
  await userEvent.click(screen.getByRole("button", { name: "Import skill" }));
  await userEvent.keyboard("{Escape}");
  expect(view.close).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Import skill" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Import skill" }));
  expect(applySkillPackage).toHaveBeenCalledTimes(1);
  await act(async () => reject(new Error("import refused")));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByRole("button", { name: "Import skill" })).toBeEnabled();
  expect(view.imported).not.toHaveBeenCalled();
});

it("ignores an empty file selection without starting a preview", () => {
  const view = setup();
  fireEvent.change(view.input(), { target: { files: [] } });
  expect(previewSkillPackage).not.toHaveBeenCalled();
});

it.each(["receipt", "invalidation"] as const)(
  "never navigates or announces an import after a tenant switch during %s",
  async (boundary) => {
    const view = setup();
    const receipt = {
      skill_id: "new",
      version_id: "v1",
      name: "template",
      files: 1,
      fingerprint: "digest",
    };
    const invalidate = vi.spyOn(view.client, "invalidateQueries");
    if (boundary === "receipt")
      vi.mocked(applySkillPackage).mockImplementationOnce(async () => {
        scope.tenant = "org-b";
        return receipt;
      });
    else
      invalidate.mockImplementationOnce(async () => {
        scope.tenant = "org-b";
      });
    fireEvent.change(view.input(), { target: { files: [new File(["body"], "SKILL.md")] } });
    await screen.findByText("assets/template.xlsx");
    await userEvent.click(screen.getByRole("button", { name: "Import skill" }));
    await waitFor(() => expect(applySkillPackage).toHaveBeenCalled());
    expect(view.imported).not.toHaveBeenCalled();
    expect(view.close).not.toHaveBeenCalled();
    if (boundary === "receipt") expect(invalidate).not.toHaveBeenCalled();
  },
);

it.each(["preview", "apply"] as const)(
  "does not report a stale %s failure in a different organization",
  async (boundary) => {
    const view = setup();
    if (boundary === "preview")
      vi.mocked(previewSkillPackage).mockImplementationOnce(async () => {
        scope.tenant = "org-b";
        throw new Error("old tenant failure");
      });
    fireEvent.change(view.input(), { target: { files: [new File(["body"], "SKILL.md")] } });
    if (boundary === "apply") {
      await screen.findByText("assets/template.xlsx");
      vi.mocked(applySkillPackage).mockImplementationOnce(async () => {
        scope.tenant = "org-b";
        throw new Error("old tenant failure");
      });
      await userEvent.click(screen.getByRole("button", { name: "Import skill" }));
    }
    await waitFor(() => expect(scope.tenant).toBe("org-b"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(view.imported).not.toHaveBeenCalled();
  },
);
