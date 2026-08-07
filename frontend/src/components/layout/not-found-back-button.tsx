"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

/**
 * The 404 page's back button.
 *
 * Its label is English in the file for the reason `app/not-found.tsx` gives:
 * the only thing that renders this sits outside `NextIntlClientProvider`, so
 * a translator here throws and turns the 404 into a 500.
 */
export function NotFoundBackButton() {
  const router = useRouter();
  return (
    <Button variant="outline" onClick={() => router.back()}>
      {/* i18n-exempt: rendered outside NextIntlClientProvider - see the docstring */}
      Go back
    </Button>
  );
}
