/** External delivery limits narrow the person's notification preferences. */
import type { ChatNotificationChannel } from "@/lib/notification-preferences-api";

export type RoutineNotificationChannel = "email" | "push" | ChatNotificationChannel;
export type WatchReportMode = "changes" | "every_check";
