"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * The confirm-and-join card both invitation paths render.
 *
 * What differs between them is the accept call handed in: the direct token page
 * calls the token accept, the staged pending page (#1414) redeems its httpOnly
 * cookie. The wording, the four states and where a success or a refusal lands are
 * the same, so they live here once rather than in two components that drift.
 */
export function InvitationAcceptCard({ accept }: { accept: () => Promise<void> }) {
  const t = useTranslations("pages.invitations");
  const router = useRouter();
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");

  const handleAccept = async () => {
    setStatus("loading");
    try {
      await accept();
      setStatus("success");
      setTimeout(() => router.push("/orgs"), 2000);
    } catch {
      setStatus("error");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>{t("teamInvitation")}</CardTitle>
          <CardDescription>{t("youAposVeBeen")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          {status === "success" && (
            <>
              <CheckCircle2 className="text-foreground h-12 w-12" />
              <p className="text-sm font-medium">{t("youJoinedOrganization")}</p>
              <p className="text-muted-foreground text-xs">{t("redirectingYourOrganizations")}</p>
            </>
          )}
          {status === "error" && (
            <>
              <XCircle className="text-destructive h-12 w-12" />
              <p className="text-sm font-medium">{t("failedAcceptInvitation")}</p>
              <p className="text-muted-foreground text-xs">{t("invitationMayHaveExpired")}</p>
              <Button variant="outline" onClick={() => router.push("/dashboard")}>
                {t("goDashboard")}
              </Button>
            </>
          )}
          {(status === "idle" || status === "loading") && (
            <>
              {status === "loading" && <Loader2 className="text-primary h-8 w-8 animate-spin" />}
              <p className="text-muted-foreground text-sm">{t("clickBelowAcceptInvitation")}</p>
              <Button onClick={handleAccept} disabled={status === "loading"} className="w-full">
                {status === "loading" ? t("joining") : t("acceptInvitation")}
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
