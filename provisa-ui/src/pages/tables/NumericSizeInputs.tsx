// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.

import { useState } from "react";
import { Group, NumberInput, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { NUMERIC_MAX_PRECISION, isNumericSize, numericSize, numericType } from "../../irTypes";

/**
 * A numeric column's precision and scale (REQ-1961). With both set the column is exact and its
 * type is `numeric(p,s)`; with both empty it declares no size and is read as an approximate
 * number. The type changes only when the two fields together say one or the other.
 */
export function NumericSizeInputs({
  dataType,
  onChange,
  disabled = false,
  testId,
}: {
  dataType: string;
  onChange: (dataType: string) => void;
  disabled?: boolean;
  testId?: string;
}) {
  const { t } = useTranslation();
  const declared = numericSize(dataType);
  const [precision, setPrecision] = useState<number | "">(declared ? declared.precision : "");
  const [scale, setScale] = useState<number | "">(declared ? declared.scale : "");

  const settle = (p: number | "", s: number | "") => {
    setPrecision(p);
    setScale(s);
    if (p === "" && s === "") onChange(numericType(null));
    else if (p !== "" && s !== "" && isNumericSize(p, s))
      onChange(numericType({ precision: p, scale: s }));
  };
  const empty = precision === "" && scale === "";
  const valid = precision !== "" && scale !== "" && isNumericSize(precision, scale);
  const asNumber = (v: number | string): number | "" => (typeof v === "number" ? v : "");

  return (
    <div data-testid={testId}>
      <Group gap={4} wrap="nowrap" mt={4}>
        <NumberInput
          aria-label={t("tableEditForm.numericPrecision")}
          placeholder={t("tableEditForm.numericPrecision")}
          value={precision}
          onChange={(v) => settle(asNumber(v), scale)}
          min={1}
          max={NUMERIC_MAX_PRECISION}
          allowDecimal={false}
          hideControls
          disabled={disabled}
          error={!empty && !valid}
          size="xs"
          w={86}
        />
        <NumberInput
          aria-label={t("tableEditForm.numericScale")}
          placeholder={t("tableEditForm.numericScale")}
          value={scale}
          onChange={(v) => settle(precision, asNumber(v))}
          min={0}
          max={NUMERIC_MAX_PRECISION}
          allowDecimal={false}
          hideControls
          disabled={disabled}
          error={!empty && !valid}
          size="xs"
          w={86}
        />
      </Group>
      <Text size="xs" c={!empty && !valid ? "red" : "dimmed"} mt={2}>
        {empty
          ? t("tableEditForm.numericSizeNone")
          : valid
            ? t("tableEditForm.numericSizeExact")
            : t("tableEditForm.numericSizeInvalid", { max: NUMERIC_MAX_PRECISION })}
      </Text>
    </div>
  );
}
