// Copyright (c) 2026 Kenneth Stott
// Canary: 6a3d9e17-b84c-4f25-a7e1-5d0b2c8f9a63
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1960: a Wikipedia source -- the pages to start from, how far to follow the links in their
// text, and every crawl setting, each with the brand's default shown until it is replaced.

import { Accordion, Checkbox, NumberInput, TextInput, Textarea } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { WIKIPEDIA_CRAWL_FIELDS, WIKIPEDIA_KNOWN_SEE_ALSO, wikipediaMissing } from "./wikipedia";
import { FormChecks, FormField, FormLayout } from "../../components/form/FormLayout";

interface Props {
  fields: Record<string, string>;
  setFields: (fields: Record<string, string>) => void;
}

export function WikipediaFields({ fields, setFields }: Props) {
  const { t } = useTranslation();
  const missing = new Set(wikipediaMissing(fields));
  const set = (key: string, value: string) => setFields({ ...fields, [key]: value });
  const text = (key: string) => ({
    value: fields[key] ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      set(key, e.currentTarget.value),
    "data-testid": `wikipedia-${key}`,
  });
  const number = (key: string) => ({
    value: fields[key] === undefined || fields[key] === "" ? "" : Number(fields[key]),
    onChange: (value: string | number) => set(key, value === "" ? "" : String(value)),
    min: 0,
    "data-testid": `wikipedia-${key}`,
  });
  const language = (fields.wp_language ?? "").trim() || "en";
  const followSeeAlso = fields.wp_follow_see_also === "true";
  return (
    <>
      <FormField hint={t("sourceFormFieldsExtended.wpPagesHelp")} size="full">
        <Textarea
          label={t("sourceFormFieldsExtended.wpPages")}
          placeholder={"List of tallest buildings\nhttps://en.wikipedia.org/wiki/Dubai"}
          required
          autosize
          minRows={2}
          error={
            missing.has("wp_pages") ? t("sourceFormFieldsExtended.wpPagesRequired") : undefined
          }
          {...text("wp_pages")}
        />
      </FormField>
      <FormField hint={t("sourceFormFieldsExtended.wpLanguageHelp")} size="medium">
        <TextInput
          label={t("sourceFormFieldsExtended.wpLanguage")}
          placeholder="en"
          {...text("wp_language")}
        />
      </FormField>
      <FormField help={t("sourceFormFieldsExtended.wpMaxDepthHelp")} size="short">
        <NumberInput
          label={t("sourceFormFieldsExtended.wpMaxDepth")}
          placeholder="1"
          {...number("wp_max_depth")}
        />
      </FormField>
      <FormField hint={t("sourceFormFieldsExtended.wpMaxPagesHelp")} size="short">
        <NumberInput
          label={t("sourceFormFieldsExtended.wpMaxPages")}
          placeholder="25"
          {...number("wp_max_pages")}
        />
      </FormField>
      <FormField hint={t("sourceFormFieldsExtended.wpContactHelp")} size="medium">
        <TextInput
          label={t("sourceFormFieldsExtended.wpContact")}
          placeholder="data-team@example.com"
          {...text("wp_contact")}
        />
      </FormField>
      <FormChecks>
        <FormField help={t("sourceFormFieldsExtended.wpFollowSeeAlsoHelp")} size="long">
          <Checkbox
            label={t("sourceFormFieldsExtended.wpFollowSeeAlso")}
            checked={followSeeAlso}
            onChange={(e) => set("wp_follow_see_also", e.currentTarget.checked ? "true" : "")}
            data-testid="wikipedia-wp_follow_see_also"
          />
        </FormField>
      </FormChecks>
      {/* Asked only of an edition whose "See also" section Provisa cannot name, and in the
          operator's terms: the section's title as a page shows it. */}
      {!followSeeAlso && !WIKIPEDIA_KNOWN_SEE_ALSO.has(language) && (
        <FormField help={t("sourceFormFieldsExtended.wpSeeAlsoHeadingHelp")} size="long">
          <TextInput
            label={t("sourceFormFieldsExtended.wpSeeAlsoHeading")}
            placeholder="Voir aussi"
            required
            error={
              missing.has("wp_see_also_heading")
                ? t("sourceFormFieldsExtended.wpSeeAlsoHeadingRequired")
                : undefined
            }
            {...text("wp_see_also_heading")}
          />
        </FormField>
      )}
      <FormField help={t("sourceFormFieldsExtended.wpDirectoryHelp")} size="long">
        <TextInput
          label={t("sourceFormFieldsExtended.wpDirectory")}
          placeholder="/data/wikipedia"
          {...text("wp_directory")}
        />
      </FormField>
      {/* The crawl's own settings all have defaults: folded away until they are wanted. */}
      <FormField size="full">
        <Accordion variant="separated" data-testid="wikipedia-crawl-settings">
          <Accordion.Item value="crawl">
            <Accordion.Control>{t("sourceFormFieldsExtended.wpCrawlSettings")}</Accordion.Control>
            <Accordion.Panel>
              <FormLayout>
                {WIKIPEDIA_CRAWL_FIELDS.map((f) => {
                  const key = `wpc_${f.key}`;
                  const label = t(`sourceFormFieldsExtended.wpCrawl.${f.key}`);
                  const description = t(`sourceFormFieldsExtended.wpCrawlHelp.${f.key}`);
                  if (f.kind === "list") {
                    return (
                      <FormField help={description} size="full" key={key}>
                        <Textarea
                          label={label}
                          placeholder={f.placeholder}
                          autosize
                          minRows={2}
                          {...text(key)}
                        />
                      </FormField>
                    );
                  }
                  return f.kind === "number" ? (
                    <FormField help={description} size="short" key={key}>
                      <NumberInput label={label} placeholder={f.placeholder} {...number(key)} />
                    </FormField>
                  ) : (
                    <FormField help={description} size="medium" key={key}>
                      <TextInput label={label} placeholder={f.placeholder} {...text(key)} />
                    </FormField>
                  );
                })}
              </FormLayout>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </FormField>
    </>
  );
}
