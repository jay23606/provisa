// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The JSON:API Explorer's summary view of a response: one card per resource, its relationship
// links, and an aggregate's values. Split out of JsonApiPage.tsx to keep that file under the
// max-lines gate.

import { Anchor, Card, Table } from "@mantine/core";
import { Tip } from "../../components/Tip";
import type { JsonApiDocument, JsonApiRelationshipRef, JsonApiResource } from "./document";

function ResourceCard({
  item,
  i,
  includedSet,
  relationshipTitle,
}: {
  item: JsonApiResource;
  i: number;
  includedSet?: Set<string>;
  relationshipTitle: (rel: string, ref: JsonApiRelationshipRef) => string;
}) {
  const rels = item.relationships ? Object.entries(item.relationships) : [];
  return (
    <Card
      id={`res-${item.type}-${item.id ?? i}`}
      withBorder
      padding={0}
      radius="sm"
      className="jsonapi-resource-card"
    >
      <div className="jsonapi-resource-header">
        <span className="jsonapi-resource-type">{item.type}</span>
        <span className="jsonapi-resource-id">#{item.id}</span>
        {rels.length > 0 && (
          <span className="jsonapi-rel-links">
            {rels.map(([relName, relData]) => {
              const ref = relData?.data;
              const refs: JsonApiRelationshipRef[] = Array.isArray(ref) ? ref : ref ? [ref] : [];
              return refs
                .filter(
                  (r: JsonApiRelationshipRef) =>
                    !includedSet || includedSet.has(`${r.type}::${r.id}`),
                )
                .map((r: JsonApiRelationshipRef) => (
                  <Tip key={`${relName}-${r.id}`} text={relationshipTitle(relName, r)}>
                    <Anchor className="jsonapi-rel-link" href={`#res-${r.type}-${r.id}`}>
                      {relName} #{r.id}
                    </Anchor>
                  </Tip>
                ));
            })}
          </span>
        )}
      </div>
      {item.attributes && (
        <div className="jsonapi-attr-scroll">
          <Table className="jsonapi-attr-table">
            <Table.Tbody>
              {Object.entries(item.attributes as Record<string, unknown>)
                .filter(([k]) => !k.startsWith("_"))
                .map(([k, v]) => (
                  <Table.Tr key={k}>
                    <Table.Td className="jsonapi-attr-key">{k}</Table.Td>
                    <Table.Td className="jsonapi-attr-val">
                      {v === null || v === undefined ? (
                        <span className="jsonapi-attr-null">null</span>
                      ) : typeof v === "object" ? (
                        JSON.stringify(v)
                      ) : (
                        String(v)
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
            </Table.Tbody>
          </Table>
        </div>
      )}
    </Card>
  );
}

export function SummaryView({
  doc,
  noResultsLabel,
  includedLabel,
  relationshipTitle,
}: {
  doc: JsonApiDocument;
  noResultsLabel: string;
  includedLabel: string;
  relationshipTitle: (rel: string, ref: JsonApiRelationshipRef) => string;
}) {
  const items: JsonApiResource[] = Array.isArray(doc.data) ? doc.data : doc.data ? [doc.data] : [];
  const included: JsonApiResource[] = Array.isArray(doc.included) ? doc.included : [];
  const includedSet = new Set<string>(included.map((r) => `${r.type}::${r.id}`));
  // REQ-1359: aggregate (non-group-by) responses have data: null, meta.aggregate: {...}.
  const aggregateMeta =
    doc.data === null ? (doc.meta?.aggregate as Record<string, unknown> | undefined) : undefined;
  if (aggregateMeta) {
    return (
      <div className="jsonapi-summary">
        <Table className="jsonapi-attr-table" data-testid="jsonapi-aggregate-table">
          <Table.Tbody>
            {Object.entries(aggregateMeta).map(([k, v]) => (
              <Table.Tr key={k}>
                <Table.Td className="jsonapi-attr-key">{k}</Table.Td>
                <Table.Td className="jsonapi-attr-val">
                  {v === null || v === undefined ? (
                    <span className="jsonapi-attr-null">null</span>
                  ) : typeof v === "object" ? (
                    JSON.stringify(v)
                  ) : (
                    String(v)
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
    );
  }
  if (items.length === 0) {
    return <div className="jsonapi-summary-empty">{noResultsLabel}</div>;
  }
  return (
    <div className="jsonapi-summary">
      {items.map((item, i) => (
        <ResourceCard
          key={`${item.type}-${item.id ?? i}`}
          item={item}
          i={i}
          includedSet={includedSet}
          relationshipTitle={relationshipTitle}
        />
      ))}
      {included.length > 0 && (
        <>
          <div className="jsonapi-included-divider">{includedLabel}</div>
          {included.map((item, i) => (
            <ResourceCard
              key={`inc-${item.type}-${item.id ?? i}`}
              item={item}
              i={i}
              relationshipTitle={relationshipTitle}
            />
          ))}
        </>
      )}
    </div>
  );
}
