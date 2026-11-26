"use client";

import { createContext, useContext } from "react";
import type { AskUserAnswer, AskUserQuestion } from "@/types/chat";

export interface QuestionInteraction {
  id: string;
  messageId: string | null;
  toolCallIds: readonly string[];
  questions: AskUserQuestion[];
  submitting: boolean;
  disabled: boolean;
  onAnswer: (answers: AskUserAnswer[]) => void;
}

export const QuestionInteractionContext = createContext<QuestionInteraction | null>(null);
export const useQuestionInteraction = () => useContext(QuestionInteractionContext);
