"use client";

import { useTranslations } from "next-intl";

import { FormField, Input, Textarea } from "@/components/ui";

interface DatasetDetailsFieldsProps {
  name: string;
  onNameChange: (name: string) => void;
  description: string;
  onDescriptionChange: (description: string) => void;
  errors: Readonly<Record<string, string>>;
  /** The guided creation's anchor on the name field; absent where no walk points at it. */
  nameTour?: string;
}

/** What a dataset is called and what it is for - the same two fields to create or to edit. */
export function DatasetDetailsFields({
  name,
  onNameChange,
  description,
  onDescriptionChange,
  errors,
  nameTour,
}: DatasetDetailsFieldsProps) {
  const t = useTranslations("datasets");
  return (
    <div className="space-y-4">
      <FormField htmlFor="dataset-name" label={t("name")} error={errors.name} required>
        <Input
          data-tour={nameTour}
          maxLength={120}
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
        />
      </FormField>
      <FormField htmlFor="dataset-description" label={t("description")} error={errors.description}>
        <Textarea
          rows={3}
          maxLength={500}
          value={description}
          onChange={(event) => onDescriptionChange(event.target.value)}
        />
      </FormField>
    </div>
  );
}
