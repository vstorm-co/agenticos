"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useInvitations, useAuth } from "@/hooks";

/**
 * Accepting an invitation, for whoever is holding the link.
 *
 * Separate from the page so it can be tested: the page's only job is to unwrap
 * `params`, and `use()` on a promise does not settle under the test renderer - so
 * anything asserted through the page passes whether or not the page works.
 *
 * **It navigates nowhere when nobody is signed in.** `AuthGuard`, which wraps every
 * dashboard route, has already sent that visitor to `/login?returnTo=<this page>`,
 * and `returnTo` is the one parameter carrying the invitation the rest of the way:
 * `registerHref` reads the token back out of it, the register form passes it on, and
 * the sign-in lands here again. This used to push `?redirect=` of its own - a name
 * nothing reads - and because it renders only once the guard has decided, that push
 * replaced the guard's. An invitee with no account then reached a bare `/register`
 * and arrived, signed up, in no organization at all (#1495).
 */
export function AcceptInvitation({ token }: { token: string }) {
  const t = useTranslations("pages.invitations");
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const { acceptInvitation } = useInvitations("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");

  const handleAccept = async () => {
    setStatus("loading");
    try {
      await acceptInvitation(token);
      setStatus("success");
      setTimeout(() => router.push("/orgs"), 2000);
    } catch {
      setStatus("error");
    }
  };

  if (!isAuthenticated) return null;

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
