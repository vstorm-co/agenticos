import { redirect } from "next/navigation";
import { ROUTES } from "@/lib/constants";

/** Preserve old personal-preferences links after consolidating settings. */
export default function AssistantSettingsPage() {
  redirect(ROUTES.SETTINGS_ACCOUNT);
}
