"use client";

import { useState } from "react";
import { Search, UserX } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import {
  Badge,
  Button,
  ConfirmDialog,
  Input,
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import { useWhatsAppCustomers } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import type { WhatsAppCustomer } from "@/types/channels";

interface WhatsAppCustomersSheetProps {
  /** The bot whose customers are shown; null closes the sheet. */
  bot: { id: string; name: string } | null;
  onClose: () => void;
}

/** What a customer is called in a sentence: the name, else the number, else the stable id. */
const called = (customer: WhatsAppCustomer) =>
  customer.profile_name ?? customer.phone ?? customer.bsuid;

/**
 * The people who wrote to a WhatsApp line with no account, for an operator who
 * manages channels: full numbers, a name that is only what the sender typed, and the
 * way to forget one.
 *
 * Forgetting is organization-wide and final, so it asks first and says so. A
 * customer who linked an account is a member and is not offered it.
 */
export function WhatsAppCustomersSheet({ bot, onClose }: WhatsAppCustomersSheetProps) {
  const t = useTranslations("pages.channels");
  const tErrors = useTranslations("errors");
  const format = useFormatter();
  const { customers, total, isLoading, hasMore, loadMore, loadingMore, search, forget } =
    useWhatsAppCustomers(bot?.id ?? null);
  const [phone, setPhone] = useState("");
  const [found, setFound] = useState<WhatsAppCustomer[] | null>(null);
  const [forgetting, setForgetting] = useState<WhatsAppCustomer | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const shown = found ?? customers;

  async function runSearch() {
    setFound(await search.mutateAsync(phone.trim()).catch(() => null));
  }

  async function confirmForget(customer: WhatsAppCustomer) {
    try {
      await forget.mutateAsync(customer.id);
      setForgetting(null);
      setFound(null);
      setRefusal(null);
    } catch (error) {
      setRefusal(getErrorMessage(error, tErrors));
    }
  }

  return (
    <Sheet open={bot !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full max-w-xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{t("customersTitle", { bot: bot?.name ?? "" })}</SheetTitle>
        </SheetHeader>
        <div className="space-y-4 p-4">
          <form
            className="flex items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void runSearch();
            }}
          >
            <div className="flex-1 space-y-1">
              <label htmlFor="customer-search" className="text-sm font-medium">
                {t("customerSearch")}
              </label>
              <Input
                id="customer-search"
                value={phone}
                inputMode="tel"
                autoComplete="off"
                onChange={(event) => setPhone(event.target.value)}
              />
            </div>
            <Button type="submit" disabled={phone.trim() === "" || search.isPending}>
              <Search className="h-4 w-4" />
              {t("customerSearchButton")}
            </Button>
            {found !== null && (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setFound(null);
                  setPhone("");
                }}
              >
                {t("customerShowAll")}
              </Button>
            )}
          </form>

          {!isLoading && shown.length === 0 && (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {found !== null ? t("customerNoMatch") : t("customersNone")}
            </p>
          )}

          <ul className="divide-y">
            {shown.map((customer) => (
              <li key={customer.id} className="flex items-start gap-3 py-3">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="text-sm font-medium">{customer.phone ?? customer.bsuid}</p>
                  {customer.profile_name && (
                    <p className="text-muted-foreground text-xs">
                      {t("customerUnverifiedName", { name: customer.profile_name })}
                    </p>
                  )}
                  {customer.username && (
                    <p className="text-muted-foreground text-xs">{customer.username}</p>
                  )}
                  <p className="text-muted-foreground text-xs">
                    {customer.last_message_at
                      ? t("customerLastMessage", {
                          when: format.dateTime(new Date(customer.last_message_at), {
                            dateStyle: "medium",
                            timeStyle: "short",
                          }),
                        })
                      : t("customerNoMessages")}
                  </p>
                  {customer.linked && (
                    <p className="text-muted-foreground text-xs">{t("customerLinkedWhy")}</p>
                  )}
                </div>
                {customer.linked ? (
                  <Badge variant="secondary">{t("customerLinked")}</Badge>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("customerForget", { name: called(customer) })}
                    onClick={() => {
                      setRefusal(null);
                      setForgetting(customer);
                    }}
                  >
                    <UserX className="h-4 w-4" />
                  </Button>
                )}
              </li>
            ))}
          </ul>

          {found === null && customers.length > 0 && (
            <div className="flex items-center justify-between gap-2">
              <p className="text-muted-foreground text-xs">
                {t("customersTotal", { shown: customers.length, total })}
              </p>
              {hasMore && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={loadingMore}
                  onClick={() => void loadMore()}
                >
                  {t("customersLoadMore")}
                </Button>
              )}
            </div>
          )}
        </div>

        <ConfirmDialog
          open={forgetting !== null}
          onOpenChange={(open) => !open && setForgetting(null)}
          title={t("customerForgetTitle", { name: forgetting ? called(forgetting) : "" })}
          description={t("customerForgetBody")}
          confirmLabel={t("customerForgetConfirm")}
          destructive
          loading={forget.isPending}
          onConfirm={() => (forgetting ? confirmForget(forgetting) : undefined)}
        >
          {refusal && <p className="text-destructive text-sm">{refusal}</p>}
        </ConfirmDialog>
      </SheetContent>
    </Sheet>
  );
}
