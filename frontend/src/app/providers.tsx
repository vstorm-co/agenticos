"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { MotionProvider, ThemeProvider } from "@/components/theme";
import { TooltipProvider } from "@/components/ui";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Data is considered fresh for 5 min → no refetch on remount/navigation.
            staleTime: 5 * 60 * 1000,
            // Keep cached data 30 min after last use for instant back-navigation.
            gcTime: 30 * 60 * 1000,
            // Don't hammer the API when the tab regains focus.
            refetchOnWindowFocus: false,
            refetchOnReconnect: "always",
            retry: 1,
          },
          mutations: {
            retry: 0,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MotionProvider>
          <TooltipProvider>{children}</TooltipProvider>
          <Toaster
            className="console-toasts"
            position="top-right"
            gap={8}
            offset={{
              top: "calc(var(--shell-inset-top, 0px) + 1rem)",
              right: "1rem",
              bottom: "5rem",
            }}
            mobileOffset={{
              top: "calc(var(--shell-inset-top, 0px) + 1rem)",
              left: "1rem",
              right: "1rem",
              bottom: "5rem",
            }}
            toastOptions={{
              style: {
                borderRadius: "0.875rem",
              },
              classNames: {
                success: "[&_[data-icon]]:text-success",
                error: "[&_[data-icon]]:text-destructive",
                warning: "[&_[data-icon]]:text-warning",
              },
            }}
          />
        </MotionProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
