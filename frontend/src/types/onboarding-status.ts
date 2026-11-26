/** Membership-scoped progress; absent fields mean an older server supplied no status. */
export interface OnboardingProgressStatus {
  completed_at?: string | null;
  current_step?: string | null;
  updated_at?: string | null;
}
