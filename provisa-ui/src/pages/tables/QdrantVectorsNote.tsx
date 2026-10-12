// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1983: the vectors of the collection a Qdrant search names -- what its "using" may name, how
// long its query vector is, and what its score is (the collection's own distance).

import { useQuery } from "@apollo/client/react";
import { List, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { FormField } from "../../components/form/FormLayout";
import { QdrantVectors } from "../../hooks/admin.graphql";

interface QdrantVector {
  name: string;
  size: number;
  distance: string;
}

/** The collection a search's text names, or "" while it names none. */
function searchedCollection(template: string): string {
  try {
    const collection = (JSON.parse(template) as { collection?: unknown }).collection;
    return typeof collection === "string" ? collection : "";
  } catch {
    // Not JSON yet: the steward is still writing it.
    return "";
  }
}

export function QdrantVectorsNote({ sourceId, template }: { sourceId: string; template: string }) {
  const { t } = useTranslation();
  const collection = searchedCollection(template);
  const { data, error } = useQuery<{ qdrantVectors: QdrantVector[] }>(QdrantVectors, {
    variables: { sourceId, collection },
    skip: !sourceId || !collection,
  });
  if (!collection) return null;
  return (
    <FormField size="full">
      <Text size="sm" fw={600}>
        {t("registerTableForm.qdrantVectors", { collection })}
      </Text>
      {error ? (
        <Text size="sm" c="red" data-testid="register-table-qdrant-vectors-error">
          {error.message}
        </Text>
      ) : (
        <List size="sm" data-testid="register-table-qdrant-vectors">
          {(data?.qdrantVectors ?? []).map((v) => (
            <List.Item key={v.name}>
              {t("registerTableForm.qdrantVector", {
                name: v.name || t("registerTableForm.qdrantUnnamedVector"),
                size: v.size,
                distance: v.distance,
              })}
            </List.Item>
          ))}
        </List>
      )}
    </FormField>
  );
}
