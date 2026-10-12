// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// The Register Table form's table choices: a source's tables in the order it lists them, under the
// heading each is listed under where it has one (REQ-1954: a ServiceNow table's theme), shown by
// name and label.

import { useTranslation } from "react-i18next";
import { tableGroups } from "./tableGroups";

interface Listed {
  name: string;
  comment: string | null;
  group?: string | null;
}

export function TableOptions<T extends Listed>({
  tables,
  isRegistered,
}: {
  tables: T[];
  isRegistered: (table: T) => boolean;
}) {
  const { t } = useTranslation();
  return tableGroups(tables).map(([group, members]) => {
    const options = members.map((tbl) => (
      <option key={tbl.name} value={tbl.name} disabled={isRegistered(tbl)}>
        {group != null && tbl.comment
          ? t("registerTableForm.tableWithLabel", { name: tbl.name, label: tbl.comment })
          : tbl.name}
      </option>
    ));
    return group == null ? (
      options
    ) : (
      <optgroup key={group} label={group}>
        {options}
      </optgroup>
    );
  });
}
