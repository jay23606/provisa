// Copyright (c) 2026 Kenneth Stott
// Canary: 5ff859fc-84e0-414d-9767-3a03fe78a631
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// A table whose replica is being built right now says "Replicating" with a spinner; one that
// is waiting its turn, has failed, or is built does not.

import { describe, expect, it } from "vitest";
import { render, screen } from "../../../test-utils/render";
import type { ReplicaBuild, ReplicaBuilds } from "../../../api/admin";
import {
  REPLICA_BUILDS_BUSY_MS,
  REPLICA_BUILDS_QUIET_MS,
  replicaBuildsInterval,
} from "../../../hooks/useAdminOpsQueries";
import en from "../../../i18n/locales/en/replicaBuild.json";
import { MOST_SHOWN_PERCENT, buildOf, replicaProgress } from "../replicaBuild";
import { ReplicatingMark } from "../ReplicatingMark";
import { ReplicaBuildLine } from "../ReplicaBuildLine";
import { ReplicaBuildsContext } from "../replicaBuildsContext";

function build(over: Partial<ReplicaBuild>): ReplicaBuild {
  return {
    sourceId: "src",
    schemaName: "public",
    tableName: "orders",
    region: null,
    state: "idle",
    requestedReason: null,
    method: null,
    loadKind: null,
    startedAt: null,
    rowsCopied: null,
    rowsPerSecond: null,
    completedRows: null,
    completedAt: null,
    verifiedAt: null,
    nextRefreshAt: null,
    lastError: null,
    lastErrorCode: null,
    lastErrorParams: null,
    failedAttempts: 0,
    nextAttemptAt: null,
    waitingOn: null,
    waitingOnCode: null,
    feedDownSince: null,
    feedError: null,
    deltaSkipped: null,
    deltaCursor: null,
    buildNotes: [],
    ...over,
  };
}

const builds = (...states: string[]): ReplicaBuilds => ({
  builds: states.map((state, i) => build({ state, tableName: `t${i}` })),
  convergenceError: null,
  convergenceErrorAt: null,
});

describe("ReplicatingMark", () => {
  const ring = () => screen.getByTestId("replicating-ring-orders");

  it("says Replicating with a ring while the build runs", () => {
    render(<ReplicatingMark build={build({ state: "building" })} />);
    const mark = screen.getByTestId("replicating-orders");
    expect(mark).toHaveTextContent(en.replicaBuild.replicating);
    expect(mark).toHaveAttribute("role", "status");
    expect(mark).toContainElement(ring());
  });

  it("fills the ring as far as the build has got against the last whole build's rows", () => {
    render(
      <ReplicatingMark
        build={build({ state: "building", rowsCopied: 12400, completedRows: 20000 })}
      />,
    );
    expect(ring()).toHaveAttribute("aria-valuenow", "62");
    // Said as an estimate: the table may have grown or shrunk since that build.
    expect(ring()).toHaveAttribute("aria-label", "About 62%: 12,400 of about 20,000 rows");
  });

  it("says on the ring that the build is waiting, and on whom", () => {
    render(
      <ReplicatingMark
        build={build({
          state: "building",
          rowsCopied: 12400,
          completedRows: 20000,
          wait: { by: "Microsoft", seconds: 87, until: "2026-10-10T12:01:27+00:00" },
        })}
      />,
    );
    expect(ring()).toHaveAttribute("aria-label", "Waiting 87 s: Microsoft is throttling the read");
    expect(ring()).toHaveAttribute("aria-valuenow", "62");
  });

  it("fills by mailboxes read where the build lands a mailbox at a time", () => {
    render(
      <ReplicatingMark
        build={build({
          state: "building",
          progress: { done: 3, total: 40, unit: "mailboxes", first: false },
        })}
      />,
    );
    expect(ring()).toHaveAttribute("aria-valuenow", "7");
    expect(ring()).toHaveAttribute("aria-label", "3 of 40 mailboxes read");
  });

  it("turns, saying the count, until the first mailbox is read to its end", () => {
    render(
      <ReplicatingMark
        build={build({
          state: "building",
          progress: { done: 0, total: 1, unit: "mailboxes", first: true },
        })}
      />,
    );
    expect(ring()).toHaveAttribute("data-turning", "true");
    expect(ring()).not.toHaveAttribute("aria-valuenow");
    expect(ring()).toHaveAttribute("aria-label", "0 of 1 mailboxes read");
  });

  it("never shows a running build as complete", () => {
    render(
      <ReplicatingMark
        build={build({ state: "building", rowsCopied: 999, completedRows: 1000 })}
      />,
    );
    expect(ring()).toHaveAttribute("aria-valuenow", String(MOST_SHOWN_PERCENT));
  });

  it("stays short of complete, and says so, once past what the last build held", () => {
    render(
      <ReplicatingMark
        build={build({ state: "building", rowsCopied: 12400, completedRows: 10000 })}
      />,
    );
    expect(ring()).toHaveAttribute("aria-valuenow", String(MOST_SHOWN_PERCENT));
    expect(ring()).toHaveAttribute("aria-label", "12,400 rows copied; the last build had 10,000");
  });

  it.each([
    ["a first build", { rowsCopied: 500, completedRows: null }, "500 rows copied"],
    ["a build that has reported no rows yet", { rowsCopied: 0, completedRows: 800 }, "Replicating"],
    ["a build with none reported at all", { rowsCopied: null, completedRows: 800 }, "Replicating"],
    ["a last build of no rows", { rowsCopied: 40, completedRows: 0 }, "40 rows copied"],
    [
      "a build that applies changes only",
      { rowsCopied: 40, completedRows: 800, method: "delta" },
      "40 rows copied",
    ],
  ])("turns without a measure, and makes up no percentage, for %s", (_what, counts, said) => {
    render(<ReplicatingMark build={build({ state: "building", ...counts })} />);
    expect(ring()).not.toHaveAttribute("aria-valuenow");
    expect(ring()).toHaveAttribute("aria-label", said);
    expect(replicaProgress(build({ state: "building", ...counts })).percent).toBeNull();
  });

  it("is one ring in both its forms: the same diameter, stroke and track", () => {
    const drawn = () => {
      const [track, arc] = [...ring().querySelectorAll("circle")];
      return {
        px: ring().getAttribute("width"),
        track: [track.getAttribute("r"), track.getAttribute("stroke-width")],
        arc: [arc.getAttribute("r"), arc.getAttribute("stroke-width")],
        turning: ring().getAttribute("data-turning"),
        spins: arc.style.animation.includes("spin"),
      };
    };
    const filling = render(
      <ReplicatingMark build={build({ state: "building", rowsCopied: 5, completedRows: 10 })} />,
    );
    const a = drawn();
    filling.unmount();
    render(<ReplicatingMark build={build({ state: "building" })} />);
    const b = drawn();
    expect([a.px, a.track, a.arc]).toEqual([b.px, b.track, b.arc]);
    expect(a.track).toEqual(a.arc);
    expect([a.px, a.turning, a.spins]).toEqual(["14", "false", false]);
    expect([b.turning, b.spins]).toEqual(["true", true]);
  });

  it("is a little larger in a table's detail than in its row", () => {
    render(<ReplicatingMark build={build({ state: "building" })} size="detail" />);
    expect(ring().getAttribute("width")).toBe("18");
  });

  it("says how far it has got on the mark itself, so the cell's own description is not shown with it", () => {
    render(
      <table>
        <tbody>
          <tr>
            <td title="Customer orders">
              <ReplicatingMark
                build={build({ state: "building", rowsCopied: 12400, completedRows: 20000 })}
              />
            </td>
          </tr>
        </tbody>
      </table>,
    );
    // The app's tooltip takes the nearest titled element from where the pointer is.
    expect(ring().closest("[title]")).toBe(screen.getByTestId("replicating-orders"));
    expect(screen.getByTestId("replicating-orders")).toHaveAttribute(
      "title",
      "About 62%: 12,400 of about 20,000 rows",
    );
  });

  it.each(["requested", "failed", "idle", "retired"])("shows nothing for a %s build", (state) => {
    render(<ReplicatingMark build={build({ state, lastError: "the source refused" })} />);
    expect(screen.queryByTestId("replicating-orders")).toBeNull();
  });

  it("shows nothing for a table with no replica record", () => {
    render(<ReplicatingMark build={undefined} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("how far a running build has got", () => {
  const of = (counts: Partial<ReplicaBuild>) =>
    replicaProgress(build({ state: "building", ...counts }));

  it("is worked out in one place, as a measure and what to say of it", () => {
    expect(of({ rowsCopied: 12400, completedRows: 20000 })).toEqual({
      percent: 62,
      // The last whole build's rows are an estimate of this build's.
      exact: false,
      said: { key: "progressAbout", numbers: { rows: 12400, total: 20000 } },
    });
    expect(of({ rowsCopied: 12400, completedRows: 10000 })).toEqual({
      percent: MOST_SHOWN_PERCENT,
      exact: false,
      said: { key: "progressPast", numbers: { rows: 12400, total: 10000 } },
    });
    expect(of({ rowsCopied: 500 })).toEqual({
      percent: null,
      exact: false,
      said: { key: "progressRows", numbers: { rows: 500 } },
    });
    expect(of({})).toEqual({
      percent: null,
      exact: false,
      said: { key: "replicating", numbers: {} },
    });
  });

  it("says a build is waiting out its source's throttle, and keeps what it had measured", () => {
    const wait = { by: "Google", seconds: 86.6, until: "2026-10-10T12:01:27+00:00" };
    expect(of({ rowsCopied: 12400, completedRows: 20000, wait })).toEqual({
      percent: 62,
      exact: false,
      said: { key: "progressWaiting", numbers: { seconds: 87 }, words: { by: "Google" } },
    });
    // With nothing measured the ring still turns; it says why nothing is arriving.
    expect(of({ wait })).toMatchObject({ percent: null, said: { key: "progressWaiting" } });
    // A wait that is over says nothing more.
    expect(of({ rowsCopied: 500, wait: null }).said.key).toBe("progressRows");
  });

  it("measures a build that lands a mailbox at a time by its mailboxes, which it knows", () => {
    const progress = { done: 3, total: 40, unit: "mailboxes", first: true };
    expect(of({ rowsCopied: 12400, completedRows: 20000, progress })).toEqual({
      percent: 7,
      // A count of what the build itself reads, not the last build's rows.
      exact: true,
      said: { key: "progressMailboxes", numbers: { done: 3, total: 40 } },
    });
    // Its last mailbox read, the build is still not complete until it says so.
    expect(of({ progress: { ...progress, done: 40 } }).percent).toBe(MOST_SHOWN_PERCENT);
    // Before its first mailbox is read to its end it turns, and still says the count.
    expect(of({ progress: { ...progress, done: 0 } })).toEqual({
      percent: null,
      exact: true,
      said: { key: "progressMailboxes", numbers: { done: 0, total: 40 } },
    });
    expect(of({ progress: { ...progress, done: 1 } }).percent).toBe(2);
    // No mailboxes to read measures nothing; the rows do, where they can.
    expect(of({ rowsCopied: 5, progress: { ...progress, total: 0 } }).said.key).toBe(
      "progressRows",
    );
    // Waiting out a throttle is still what it says first.
    const wait = { by: "Google", seconds: 30, until: "2026-10-10T12:00:30+00:00" };
    expect(of({ progress, wait })).toMatchObject({
      percent: 7,
      exact: true,
      said: { key: "progressWaiting" },
    });
  });

  it("measures a Logs source's build by the files it reads", () => {
    const progress = { done: 2, total: 8, unit: "files", first: false };
    expect(of({ progress })).toEqual({
      percent: 25,
      exact: true,
      said: { key: "progressFiles", numbers: { done: 2, total: 8 } },
    });
  });

  it("has wording for everything it says", () => {
    const keys = [
      "progressAbout",
      "progressPast",
      "progressRows",
      "progressMailboxes",
      "progressFiles",
      "progressWaiting",
      "replicating",
    ] as const;
    for (const key of keys) expect(en.replicaBuild[key]).toBeTruthy();
  });
});

describe("which build is a table's", () => {
  it("is the one of its source, schema and table name", () => {
    const mine = build({ sourceId: "a", schemaName: "s", tableName: "orders", state: "building" });
    const others = [
      build({ sourceId: "b", schemaName: "s", tableName: "orders" }),
      build({ sourceId: "a", schemaName: "other", tableName: "orders" }),
      mine,
    ];
    expect(buildOf(others, { sourceId: "a", schemaName: "s", tableName: "orders" })).toBe(mine);
    expect(buildOf(others, { sourceId: "a", schemaName: "s", tableName: "x" })).toBeUndefined();
    // Builds that could not be read (a caller without the right to see them) name none.
    expect(
      buildOf(undefined, { sourceId: "a", schemaName: "s", tableName: "orders" }),
    ).toBeUndefined();
  });
});

describe("how often builds are asked for", () => {
  it("is often while one is running or waiting, or a detail is open", () => {
    expect(replicaBuildsInterval(builds("idle", "building"), false)).toBe(REPLICA_BUILDS_BUSY_MS);
    expect(replicaBuildsInterval(builds("requested"), false)).toBe(REPLICA_BUILDS_BUSY_MS);
    expect(replicaBuildsInterval(builds("idle"), true)).toBe(REPLICA_BUILDS_BUSY_MS);
  });

  it("is seldom while nothing is, so a build that starts later still shows", () => {
    expect(replicaBuildsInterval(builds("idle", "failed", "retired"), false)).toBe(
      REPLICA_BUILDS_QUIET_MS,
    );
    expect(replicaBuildsInterval(null, false)).toBe(REPLICA_BUILDS_QUIET_MS);
    expect([REPLICA_BUILDS_BUSY_MS, REPLICA_BUILDS_QUIET_MS]).toEqual([5000, 30000]);
  });
});

describe("the table form's build line", () => {
  // The line reads what the table list last read: one request serves the list and the form.
  const line = (...builds: ReplicaBuild[]) => (
    <ReplicaBuildsContext.Provider
      value={{ builds, convergenceError: null, convergenceErrorAt: null }}
    >
      <ReplicaBuildLine sourceId="src" schemaName="public" tableName="orders" />
    </ReplicaBuildsContext.Provider>
  );

  it("has the ring in front of it while the build runs", () => {
    render(line(build({ state: "building", rowsCopied: 10, rowsPerSecond: 2 })));
    const mark = screen.getByTestId("replicating-orders");
    const text = screen.getByTestId("replica-build-line");
    expect(mark.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps its failure and shows no ring when the build fails", () => {
    render(line(build({ state: "failed", lastError: "the source refused", failedAttempts: 1 })));
    expect(screen.queryByTestId("replicating-orders")).toBeNull();
    expect(screen.getByTestId("replica-build-line")).toHaveTextContent("the source refused");
  });

  it("says nothing where builds are not known, and asks the server for nothing itself", () => {
    render(<ReplicaBuildLine sourceId="src" schemaName="public" tableName="orders" />);
    expect(screen.queryByTestId("replica-build-line")).toBeNull();
  });
});
