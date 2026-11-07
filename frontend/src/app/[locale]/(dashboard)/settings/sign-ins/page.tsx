import { MySignIns } from "@/components/browser/my-sign-ins";

/**
 * Your kept browser sign-ins (#2129).
 *
 * Under `/settings/` because they are yours rather than the organization's: a
 * sign-in is kept for the person who made it and used only by browses acting as
 * them, so no permission gates the page.
 */
export default function SignInsPage() {
  return <MySignIns />;
}
