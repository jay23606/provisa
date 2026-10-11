// Copyright (c) 2026 Kenneth Stott
// Canary: de01c519-7cda-4018-baee-2f0cbc306664
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A table whose replica is being built right now says so: a small ring and "Replicating", in
// the table list's row and in the table's detail. The ring fills as far as the build has got
// where there is something to measure it against -- the rows of the last build that copied the
// whole table, an estimate -- and turns without a measure where there is not: a first build, a
// build that reports no rows until it ends, a build that applies changes only. No percentage
// is ever made up. Shown for a running build only -- one that is waiting its turn or has failed
// is not replicating -- and gone when the build ends.

import { Group, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import type { ReplicaBuild } from "../../api/admin";
import { replicaProgress } from "./replicaBuild";

/** The ring's outer diameter and stroke, in pixels: in a list row, and in a table's detail. */
const SIZES = { row: { px: 14, stroke: 2 }, detail: { px: 18, stroke: 2.5 } } as const;
/** How much of the ring the arc covers while it turns without a measure. */
const TURNING_SHARE = 0.25;

/** One ring for both forms: a track, and an arc on it that covers `percent` of the way round
 * from the top, or -- with no measure -- a quarter that turns. Same diameter, stroke and track
 * either way, so it reads as one indicator in two states. */
function Ring({
  percent,
  size,
  label,
  testId,
}: {
  percent: number | null;
  size: keyof typeof SIZES;
  label: string;
  testId: string;
}) {
  const { px, stroke } = SIZES[size];
  const radius = (px - stroke) / 2;
  const around = 2 * Math.PI * radius;
  const share = percent === null ? TURNING_SHARE : percent / 100;
  const circle = { cx: px / 2, cy: px / 2, r: radius, fill: "none", strokeWidth: stroke };
  return (
    <svg
      width={px}
      height={px}
      viewBox={`0 0 ${px} ${px}`}
      role="progressbar"
      aria-label={label}
      {...(percent === null
        ? {}
        : { "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": percent })}
      data-testid={testId}
      data-turning={percent === null ? "true" : "false"}
      style={{ flex: "none", display: "block" }}
    >
      <circle {...circle} stroke="var(--mantine-color-default-border)" />
      <circle
        {...circle}
        stroke="var(--mantine-color-blue-filled)"
        strokeLinecap="round"
        strokeDasharray={`${around * share} ${around}`}
        // From the top of the ring, clockwise.
        style={{
          transformOrigin: "center",
          transform: "rotate(-90deg)",
          ...(percent === null ? { animation: "spin 1s linear infinite" } : {}),
        }}
      />
    </svg>
  );
}

export function ReplicatingMark({
  build,
  size = "row",
}: {
  build: ReplicaBuild | undefined;
  size?: keyof typeof SIZES;
}) {
  const { t, i18n } = useTranslation();
  if (build?.state !== "building") return null;
  const numbers = new Intl.NumberFormat(i18n.language);
  const progress = replicaProgress(build);
  const said = t(`replicaBuild.${progress.said.key}`, {
    percent: progress.percent,
    ...progress.said.words,
    ...Object.fromEntries(
      Object.entries(progress.said.numbers).map(([name, n]) => [name, numbers.format(n)]),
    ),
  });
  return (
    // `title` is shown by the app's own tooltip (components/TitleTooltips), which takes the
    // nearest titled element: on the mark it is the mark's, not that of the cell it sits in.
    <Group
      component="span"
      gap="0.25rem"
      wrap="nowrap"
      display="inline-flex"
      role="status"
      title={said}
      data-testid={`replicating-${build.tableName}`}
    >
      <Ring
        percent={progress.percent}
        size={size}
        label={said}
        testId={`replicating-ring-${build.tableName}`}
      />
      {/* The list's name cell is set in a fixed-width face; the mark is not part of the name. */}
      <Text span size="xs" c="dimmed" lh={1} ff="var(--mantine-font-family)">
        {t("replicaBuild.replicating")}
      </Text>
    </Group>
  );
}
