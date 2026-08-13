"use client";

import { useState } from "react";
import { AlertTriangle, Lock } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
  Button,
  FormField,
  Input,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { SectionCard } from "@/components/settings/settings-section";
import { useAuth } from "@/hooks";
import { apiClient, ApiError } from "@/lib/api-client";
import { useTranslations } from "next-intl";

export default function AccountSettingsPage() {
  const tErrors = useTranslations("errors");

  const t = useTranslations("pages.settings");
  const { user, logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleChangePassword = async () => {
    if (newPassword.length < 8) {
      toast.error(t("newPasswordMustBe"));
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error(t("passwordsDoNotMatch"));
      return;
    }
    setSaving(true);
    try {
      await apiClient.post("/auth/password/change", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success(t("passwordUpdated"));
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      // Backend may not have this endpoint yet - surface a helpful message.
      if (err instanceof ApiError && err.status === 404) {
        toast.error(t("passwordChangeRequiresBackend"));
      } else {
        toast.error(
          err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedUpdatePassword"),
        );
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!user) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/users/${user.id}`);
      toast.success(t("accountDeleted"));
      logout();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast.error(t("selfDeleteNotEnabled"));
      } else {
        toast.error(
          err instanceof ApiError ? getErrorMessage(err, tErrors) : t("failedDeleteAccount"),
        );
      }
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <SectionCard
        title={t("changePassword")}
        description={t("useStrongUniquePassword")}
        action={
          <Button
            onClick={handleChangePassword}
            disabled={saving || !currentPassword || !newPassword}
            size="sm"
          >
            {saving ? t("saving2") : t("updatePassword")}
          </Button>
        }
      >
        <div className="space-y-4">
          <FormField label={t("currentPassword")} htmlFor="current-pw">
            <Input
              id="current-pw"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label={t("newPassword")} htmlFor="new-pw">
              <Input
                id="new-pw"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
            </FormField>
            <FormField label={t("confirmNewPassword")} htmlFor="confirm-pw">
              <Input
                id="confirm-pw"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </FormField>
          </div>
        </div>
      </SectionCard>

      <SectionCard title={t("signOutEverywhere")} description={t("revokeEveryActiveSession")}>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="outline" size="sm">
              <Lock className="mr-2 h-3.5 w-3.5" />
              {t("signOutEverywhere")}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("signOutFromAll")}</AlertDialogTitle>
              <AlertDialogDescription>{t("revokesEveryActiveSession")}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
              <AlertDialogAction
                onClick={async () => {
                  try {
                    await apiClient.delete("/sessions");
                    toast.success(t("signedOutFromAll"));
                    logout();
                  } catch {
                    toast.error(t("failedSignOutEverywhere"));
                  }
                }}
              >
                {t("signOutEverywhere2")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </SectionCard>

      <SectionCard title={t("deleteAccount")} description={t("permanentlyRemoveYourAccount")}>
        <div className="border-border bg-muted flex items-start gap-3 rounded-xl border p-4">
          <span className="bg-card border-border text-muted-foreground flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-foreground text-sm font-semibold">{t("irreversible")}</p>
            <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">
              {t("allConversationsKnowledgeBase")}
            </p>
          </div>
        </div>
        <div className="mt-4">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="sm">
                {t("deleteMyAccount")}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t("deleteYourAccount")}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t("yourConversationsKnowledgeBase")}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t("cancel2")}</AlertDialogCancel>
                <AlertDialogAction
                  disabled={deleting}
                  onClick={handleDeleteAccount}
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  {deleting ? t("deleting") : t("yesDeleteMyAccount")}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </SectionCard>
    </div>
  );
}
