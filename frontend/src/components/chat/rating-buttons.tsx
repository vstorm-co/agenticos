"use client";
import { useState, useCallback, useMemo } from "react";
import { Loader2, ThumbsUp, ThumbsDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { getErrorMessage } from "@/lib/api-error";
import { useMessageRating } from "@/hooks/use-message-rating";
import { toast } from "sonner";
import { RatingValue, type UserRating } from "@/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

interface RatingButtonsProps {
  messageId: string;
  conversationId: string;
  currentRating: UserRating;
  ratingCount?: { likes: number; dislikes: number };
  onRatingChange?: (data: {
    rating: UserRating;
    rating_count: { likes: number; dislikes: number };
  }) => void;
  isAssistant: boolean;
}

export function RatingButtons({
  messageId,
  conversationId,
  currentRating,
  ratingCount,
  onRatingChange,
  isAssistant,
}: RatingButtonsProps) {
  const t = useTranslations("chat");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { rateMessage, removeRating } = useMessageRating(conversationId, messageId);
  const [showCommentDialog, setShowCommentDialog] = useState(false);
  const [pendingRating, setPendingRating] = useState<RatingValue>(RatingValue.DISLIKE);
  const [comment, setComment] = useState("");
  // Which button's request is in flight, not what the rating is: keying the
  // spinner on currentRating (null on an unrated message) spins both thumbs.
  const [inFlight, setInFlight] = useState<RatingValue | null>(null);

  const calculateNewCounts = useMemo(
    () =>
      (oldRating: UserRating, newRating: UserRating): { likes: number; dislikes: number } => {
        const likes = ratingCount?.likes ?? 0;
        const dislikes = ratingCount?.dislikes ?? 0;

        let newLikes = likes;
        let newDislikes = dislikes;
        if (oldRating === RatingValue.LIKE) newLikes -= 1;
        if (oldRating === RatingValue.DISLIKE) newDislikes -= 1;

        if (newRating === RatingValue.LIKE) newLikes += 1;
        if (newRating === RatingValue.DISLIKE) newDislikes += 1;

        return { likes: Math.max(0, newLikes), dislikes: Math.max(0, newDislikes) };
      },
    [ratingCount],
  );

  // submitRating must be declared before handleRate since handleRate uses it
  const submitRating = useCallback(
    async (rating: RatingValue, commentText: string | null) => {
      setInFlight(rating);
      try {
        await rateMessage({ rating, comment: commentText });
        const newCounts = calculateNewCounts(currentRating, rating);
        onRatingChange?.({ rating, rating_count: newCounts });
        toast.success(t("thankYouFeedback"));
        setShowCommentDialog(false);
        setComment("");
      } catch (error) {
        toast.error(getErrorMessage(error, tErrors));
      } finally {
        setInFlight(null);
      }
    },
    [rateMessage, currentRating, calculateNewCounts, onRatingChange, t, tErrors],
  );

  // No guard against a missing conversation id here: both buttons are
  // `disabled` while there is none, which is what stops the click *and* says
  // why in the tooltip. A second check inside the handler was unreachable, and
  // an unreachable guard is a guard nobody maintains.
  const handleRate = useCallback(
    async (rating: RatingValue) => {
      if (currentRating === rating) {
        setInFlight(rating);
        try {
          await removeRating();
          const newCounts = calculateNewCounts(currentRating, null);
          onRatingChange?.({ rating: null, rating_count: newCounts });
          toast.success(t("ratingRemoved"));
        } catch (error) {
          toast.error(getErrorMessage(error, tErrors));
        } finally {
          setInFlight(null);
        }
      } else {
        setPendingRating(rating);
        if (rating === RatingValue.DISLIKE) {
          setShowCommentDialog(true);
        } else {
          submitRating(rating, null);
        }
      }
    },
    [removeRating, currentRating, calculateNewCounts, onRatingChange, submitRating, t, tErrors],
  );

  const handleCloseDialog = useCallback(() => {
    setShowCommentDialog(false);
    setComment("");
  }, []);

  if (!isAssistant) return null;

  // Disable rating if conversationId is not set (e.g., new conversation not yet saved)
  const isMissingConversationId = !conversationId || conversationId === "";

  return (
    <>
      <div className="flex items-center gap-1">
        <button
          onClick={() => handleRate(RatingValue.LIKE)}
          disabled={inFlight !== null || isMissingConversationId}
          className={cn(
            "inline-flex items-center rounded-md p-1.5 transition-colors",
            "hover:bg-muted/80",
            "opacity-100 sm:opacity-0 sm:group-hover:opacity-100",
            currentRating === RatingValue.LIKE && "bg-success/25 text-success",
            isMissingConversationId && "cursor-not-allowed opacity-50",
          )}
          title={isMissingConversationId ? t("saveConversationToRate") : t("helpful")}
        >
          {inFlight === RatingValue.LIKE ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <ThumbsUp className="h-4 w-4" />
          )}
          {ratingCount && ratingCount.likes > 0 && (
            <span className="ml-1 text-xs">{ratingCount.likes}</span>
          )}
        </button>

        <button
          onClick={() => handleRate(RatingValue.DISLIKE)}
          disabled={inFlight !== null || isMissingConversationId}
          className={cn(
            "inline-flex items-center rounded-md p-1.5 transition-colors",
            "hover:bg-muted/80",
            "opacity-100 sm:opacity-0 sm:group-hover:opacity-100",
            currentRating === RatingValue.DISLIKE && "bg-destructive/25 text-destructive",
            isMissingConversationId && "cursor-not-allowed opacity-50",
          )}
          title={isMissingConversationId ? t("saveConversationToRate") : t("notHelpful")}
        >
          {inFlight === RatingValue.DISLIKE ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <ThumbsDown className="h-4 w-4" />
          )}
          {ratingCount && ratingCount.dislikes > 0 && (
            <span className="ml-1 text-xs">{ratingCount.dislikes}</span>
          )}
        </button>
      </div>

      <Dialog open={showCommentDialog} onOpenChange={setShowCommentDialog}>
        <DialogContent className={DIALOG_CONFIRM}>
          <DialogHeader>
            <DialogTitle>{t("whatWentWrong")}</DialogTitle>
            <DialogDescription>{t("feedbackHelp")}</DialogDescription>
          </DialogHeader>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t("describeIssue")}
            className="bg-background min-h-[100px] w-full rounded-md border p-2"
            maxLength={2000}
            autoFocus
          />
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground text-xs">{comment.length} / 2000</span>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={handleCloseDialog} disabled={inFlight !== null}>
                {tc("cancel")}
              </Button>
              <Button
                variant="outline"
                onClick={() => submitRating(pendingRating, null)}
                disabled={inFlight !== null}
              >
                {inFlight !== null ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {t("skipComment")}
              </Button>
              <Button
                onClick={() => submitRating(pendingRating, comment.trim() || null)}
                disabled={inFlight !== null}
              >
                {inFlight !== null ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {tc("submit")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
