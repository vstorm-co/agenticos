"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
} from "@/components/ui";
import { useSignInToSite } from "@/hooks/use-browser-sign-ins";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

/** A bare host typed into the box is a site; the browser needs an address. */
function asAddress(typed: string): string {
  const trimmed = typed.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

/**
 * Sign in to a site in a browser of your own, before any agent needs it (#2129).
 *
 * Opens the deployment's browser on the address given and takes the person to
 * its live view, already holding it. They sign in there and hand it back with
 * "Keep me signed in"; from then on their agents' browses start signed in.
 */
export function SignInToSiteDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("pages.signIns");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { start, isStarting } = useSignInToSite();
  const [address, setAddress] = useState("");
  const [problem, setProblem] = useState<string | undefined>();

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (address.trim() === "") return;
    try {
      const session = await start(asAddress(address));
      router.push(`/browse/${session.run_id}/${session.call_id}`);
    } catch (error) {
      const failure = submitFailure(error, { fields: ["url"] }, tErrors);
      setProblem(failure.fields.url);
      if (failure.toast) toast.error(failure.toast);
    }
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("signInTitle")}</DialogTitle>
          <DialogDescription>{t("signInDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <FormField label={t("siteLabel")} htmlFor="sign-in-site" error={problem}>
            <Input
              id="sign-in-site"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value);
                setProblem(undefined);
              }}
              placeholder={t("sitePlaceholder")}
              inputMode="url"
            />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={address.trim() === "" || isStarting}>
              {t("openBrowser")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
