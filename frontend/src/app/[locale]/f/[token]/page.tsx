import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { FormSurface } from "@/components/workflows/form-surface";
import { PublicForm, type PublicFormPage } from "@/components/workflows/public-form";

/**
 * A workflow's form behind its public link.
 *
 * Outside `(dashboard)` for the reason `/a/[publicKey]` is: no session, no
 * organization, none of the console. The form is read server-side and never
 * cached, so a replaced link or a paused form stops answering at once.
 */
interface PublicFormPageProps {
  params: Promise<{ token: string; locale: string }>;
}

/** One request per visit, shared by the metadata and the render. */
const fetchForm = cache(async (token: string): Promise<PublicFormPage | null> => {
  // `secrets.token_urlsafe` minted the link, so anything outside its alphabet
  // is not one this deployment made.
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(token)) return null;
  const baseUrl = process.env.BACKEND_URL || "http://localhost:8000";
  const response = await fetch(
    `${baseUrl}/api/v1/public/workflow-forms/${encodeURIComponent(token)}`,
    { cache: "no-store" },
  );
  // A replaced, paused or never-made link are one answer. Anything else is not
  // the form being gone, so it reaches the error boundary instead.
  if (response.status === 404) return null;
  if (!response.ok) {
    // i18n-exempt: an Error message for the boundary and the logs, never rendered copy.
    throw new Error(`Form request failed with ${response.status}`);
  }
  return (await response.json()) as PublicFormPage;
});

export async function generateMetadata({ params }: PublicFormPageProps): Promise<Metadata> {
  const { token } = await params;
  const page = await fetchForm(token);
  return {
    title: page?.title ?? undefined,
    // The link is the whole of what protects the form; a crawler that followed
    // one would publish it.
    robots: { index: false, follow: false },
  };
}

export default async function WorkflowFormPage({ params }: PublicFormPageProps) {
  const { token } = await params;
  const page = await fetchForm(token);
  if (page === null) notFound();
  return (
    <main className="bg-muted/20 min-h-screen px-4 py-10 sm:px-6 sm:py-20">
      <FormSurface appearance={page.appearance}>
        <PublicForm page={page} token={token} />
      </FormSurface>
    </main>
  );
}
