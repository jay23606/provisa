// Copyright (c) 2026 Kenneth Stott
// Canary: fa9a9028-ab4a-45ba-990b-c9d20cca9b24
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-2010: a named demo tells its own story first. Its steps, written with the demo, become steps
// of the tour runner pointing at the demo's own objects; the tour button runs them before the
// product tour until they have been walked to their end, and the Deep Dives menu lists them first.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useNavPayload } from "../hooks/useNavPayload";
import { MantineProvider } from "@mantine/core";
import { demoTourSteps, type DemoTourStepDef } from "../tour/demoTour";
import { NamedDemoContext, type NamedDemo } from "../context/NamedDemoContext";
import { storageKey } from "../lib/browserStorage";
import type { OrgHas } from "../tour/tourPrerequisites";

const t = (key: string) => key;
// REQ-2013: the org has every object the product tour's steps show.
// REQ-2013: the org of each test: the weblogs demo's, unless a test names another.
const org = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("../hooks/useOrgHas", () => {
  // One function, as the hook's useCallback gives: a new one each render re-runs the tour's step.
  const read = () => Promise.resolve(org.current);
  return { useOrgHas: () => read };
});
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));

let chunksResolve: () => void = () => {};
vi.mock("../pageChunks", () => ({
  prefetchAllPageChunks: () =>
    new Promise<void>((resolve) => {
      chunksResolve = resolve;
    }),
}));
vi.mock("../hooks/useAdminQueries", () => ({ useTourPrefetch: () => () => Promise.resolve() }));
vi.mock("../context/pollyState", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../context/pollyState")>()),
  usePolly: () => ({
    open: false,
    checkingConfig: false,
    unconfiguredReason: null,
    setUnconfiguredReason: () => {},
    openPolly: () => Promise.resolve(),
    closePolly: () => {},
  }),
}));
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    loading: false,
    capabilities: ["source_registration", "create_relationship", "query_development"],
  }),
}));

const { TourProvider, useTour } = await import("../tour/useTour");

beforeEach(() => {
  org.current = WEBLOGS_ORG;
});
const { TourMenu } = await import("../tour/TourMenu");

const EXAMPLES = [{ name: "1-slowest-pages-by-path", query: "query SlowestPagesByPath { a }" }];

describe("a demo's steps, as the runner walks them", () => {
  it("points each target at the demo's object on its page", () => {
    const defs: DemoTourStepDef[] = [
      { key: "a", route: "/sources", capability: "source_registration", source: "shop_access" },
      { key: "b", relationship: "LOGGED_FOR" },
      { key: "c", route: "/query", capability: "query_development", example: EXAMPLES[0].name },
      { key: "d", route: "/sql", capability: "query_development", sql: "SELECT 1" },
      { key: "e", role: "analyst" },
    ];
    const [source, relationship, example, sql, role] = demoTourSteps(defs, EXAMPLES);
    expect(source).toEqual({
      key: "a",
      route: "/sources",
      capability: "source_registration",
      element: '[data-testid="sources-row-shop_access"]',
    });
    expect(relationship).toEqual({ key: "b", element: '[data-tour-relationship="LOGGED_FOR"]' });
    expect(example.openQuery).toEqual({ stateKey: "query", text: EXAMPLES[0].query });
    expect(example.element).toBe(".graphiql-response");
    expect(sql.openQuery).toEqual({ stateKey: "sql", text: "SELECT 1" });
    // The rows of the run, not the table an unrun tab already shows.
    expect(sql.readySelector).toContain("tbody tr:not(");
    // The picker is shown; Next opens it and picks the role.
    expect(role.element).toBe('[data-testid="sql-role"]');
    expect(role.chooseOnNext).toEqual({
      open: '[data-testid="sql-role"]',
      option: '[data-sql-role-option="analyst"]',
    });
  });

  it("refuses a step naming an example the demo does not ship", () => {
    expect(() => demoTourSteps([{ key: "x", example: "9-missing" }], EXAMPLES)).toThrow(
      /names example "9-missing"/,
    );
  });
});

const WEBLOGS_ORG: OrgHas = {
  sources: new Set(["shop-db", "shop_access", "shop_db_log"]),
  tables: new Set(["shop-db.customers", "shop_access.shop_access"]),
  dataProducts: 0,
};

const WEBLOGS: NamedDemo = {
  name: "weblogs",
  exampleQueries: EXAMPLES,
  tour: [
    {
      key: "weblogsSources",
      route: "/sources",
      capability: "source_registration",
      source: "shop_access",
    },
    { key: "weblogsDbLog", source: "shop_db_log" },
  ],
};

function Launcher() {
  const { startTour } = useTour();
  return (
    <>
      <button type="button" onClick={() => startTour()}>
        launch
      </button>
      {/* The welcome modal's Start, and ?tour=1. */}
      <button type="button" onClick={() => startTour({ restart: true })}>
        start
      </button>
    </>
  );
}

function renderTour(demo: NamedDemo) {
  return render(
    <MantineProvider>
      <MemoryRouter>
        <NamedDemoContext.Provider value={demo}>
          <TourProvider>
            <Launcher />
            {/* The demo's objects, as the Sources page paints them. */}
            <table>
              <tbody>
                <tr data-testid="sources-row-shop_access" />
                <tr data-testid="sources-row-shop_db_log" />
              </tbody>
            </table>
          </TourProvider>
        </NamedDemoContext.Provider>
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe("the tour button in a named demo", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it("tells the demo's story first, and returns to the menu at its end", async () => {
    renderTour(WEBLOGS);
    fireEvent.click(screen.getByText("launch"));
    await act(async () => chunksResolve());
    expect(await screen.findByText("tour.steps.weblogsSources.title")).toBeInTheDocument();

    fireEvent.click(document.querySelector<HTMLElement>(".driver-popover-next-btn")!);
    expect(await screen.findByText("tour.steps.weblogsDbLog.title")).toBeInTheDocument();
    fireEvent.click(document.querySelector<HTMLElement>(".driver-popover-next-btn")!);

    // Walked to its end in this demo: the menu opens, the track marked done.
    expect(await screen.findByTestId("tour-menu")).toBeInTheDocument();
    expect(localStorage.getItem(storageKey("provisa_tour_demo_track_done"))).toBe("true");
  });

  it("opens the menu once the demo's track is done, the product tour not offered", async () => {
    // REQ-2013: the weblogs demo has none of the standard demo's pet store, which the product
    // tour's query card shows.
    localStorage.setItem(storageKey("provisa_tour_demo_track_done"), "true");
    renderTour(WEBLOGS);
    fireEvent.click(screen.getByText("launch"));
    await act(async () => chunksResolve());
    expect(await screen.findByTestId("tour-menu")).toBeInTheDocument();
    expect(screen.queryByText("tour.steps.weblogsSources.title")).toBeNull();
    expect(screen.queryByTestId("tour-menu-core-tour")).toBeNull();
    expect(screen.getByTestId("tour-demo-track-done")).toBeInTheDocument();
  });

  it("runs the product tour where no named demo has a tour", async () => {
    const { STANDARD_DEMO_ORG } = await import("../test-utils/tourOrg");
    org.current = STANDARD_DEMO_ORG;
    renderTour({ name: null, exampleQueries: [], tour: [] });
    fireEvent.click(screen.getByText("launch"));
    await act(async () => chunksResolve());
    await act(async () => vi.advanceTimersByTime(2000));
    expect(screen.queryByText("tour.steps.weblogsSources.title")).toBeNull();
    // The product tour's first step is under way instead (its page is not mounted here).
    expect(screen.getByText("tour.status.waiting")).toBeInTheDocument();
  });
});

describe("starting the tour from the top in a named demo", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("starts with the demo's story, even once it has been walked", async () => {
    localStorage.setItem(storageKey("provisa_tour_demo_track_done"), "true");
    renderTour(WEBLOGS);
    fireEvent.click(screen.getByText("start"));
    await act(async () => chunksResolve());
    expect(await screen.findByText("tour.steps.weblogsSources.title")).toBeInTheDocument();
  });
});

describe("a demo step's statement", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("is handed to its explorer once for each visit to the step", async () => {
    const delivered: unknown[] = [];
    function Explorer() {
      useNavPayload<{ sql?: string }>((payload) => delivered.push(payload.sql));
      return <table className="sql-results-table" />;
    }
    render(
      <MantineProvider>
        {/* Entered from another page, as the tour enters an explorer: the move re-renders the
            router, which re-runs the step. */}
        <MemoryRouter initialEntries={["/sources"]}>
          <NamedDemoContext.Provider
            value={{
              name: "weblogs",
              exampleQueries: [],
              tour: [
                { key: "s1", route: "/sql", capability: "query_development", sql: "SELECT 1" },
              ],
            }}
          >
            <TourProvider>
              <Launcher />
              <Routes>
                <Route path="/sql" element={<Explorer />} />
              </Routes>
            </TourProvider>
          </NamedDemoContext.Provider>
        </MemoryRouter>
      </MantineProvider>,
    );
    fireEvent.click(screen.getByText("launch"));
    await act(async () => chunksResolve());
    await act(async () => new Promise((r) => setTimeout(r, 300)));
    // Handing it over moves the router, which re-runs the step: the statement opens once, not twice.
    expect(delivered).toEqual(["SELECT 1"]);
  });
});

describe("the Deep Dives menu in a named demo", () => {
  it("lists the demo's track first, marked done once walked", () => {
    const onDemo = vi.fn();
    render(
      <MantineProvider>
        <TourMenu
          opened
          topics={[{ id: "connect", steps: 4 }]}
          completed={[]}
          demo={{ name: "weblogs", steps: 10, done: true }}
          onDemo={onDemo}
          onPick={() => {}}
          onCore={() => {}}
          onClose={() => {}}
        />
      </MantineProvider>,
    );
    const track = screen.getByTestId("tour-demo-track");
    expect(track.compareDocumentPosition(screen.getByTestId("tour-topic-connect"))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(screen.getByText("tour.demos.weblogs.title")).toBeInTheDocument();
    expect(screen.getByTestId("tour-demo-track-done")).toBeInTheDocument();
    fireEvent.click(track);
    expect(onDemo).toHaveBeenCalledOnce();
  });
});
