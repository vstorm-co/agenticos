"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { CustomerErasure, WhatsAppCustomer } from "@/types/channels";

const PAGE_SIZE = 50;

interface CustomerList {
  items: WhatsAppCustomer[];
  total: number;
}

/**
 * The people who wrote to one WhatsApp bot with no account, and what an operator
 * may do about them.
 *
 * The number is read from a body, never a URL: a search carries it in a POST so it
 * stays out of access logs and request traces. Forgetting refuses in the open - a
 * linked customer is a member - so that mutation leaves its refusal to the sheet
 * showing the confirmation rather than toasting it away.
 */
export function useWhatsAppCustomers(botId: string | null) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  const queryClient = useQueryClient();
  const base = `/channels/bots/${botId}/whatsapp-customers`;
  const id = botId ?? "";

  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: qk.channelBots.whatsappCustomers(id),
    queryFn: ({ pageParam }) =>
      apiClient.get<CustomerList>(`${base}?skip=${pageParam}&limit=${PAGE_SIZE}`),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((count, page) => count + page.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    enabled: botId !== null,
  });

  const search = useMutation({
    mutationFn: async (phone: string) =>
      (await apiClient.post<CustomerList>(`${base}/search`, { phone })).items,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const forget = useMutation({
    mutationFn: (customerId: string) =>
      apiClient.post<CustomerErasure>(`${base}/forget`, { customer_id: customerId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: qk.channelBots.whatsappCustomers(id),
      });
      toast.success(t("customerForgotten"));
    },
  });

  return {
    customers: data?.pages.flatMap((page) => page.items) ?? [],
    total: data?.pages[0]?.total ?? 0,
    isLoading,
    hasMore: hasNextPage,
    loadMore: fetchNextPage,
    loadingMore: isFetchingNextPage,
    search,
    forget,
  };
}
