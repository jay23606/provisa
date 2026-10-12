// Copyright (c) 2026 Kenneth Stott
// Canary: dffb8002-22f3-460c-ab22-232e4a40216d
//
// This source code is licensed under the Business Source License 1.1

// REQ-1996: a Logs source is in the source pick list under File; its form names the files and
// their format, a pattern when the format is the source's own, and shows what the files hold
// before the source is saved.

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, renderInForm, screen, waitFor } from "../../../test-utils/render";
import { LogsFields } from "../LogsFields";
import { SOURCE_TYPES } from "../constants";
import { logsFieldsFromMapping, logsMapping, logsMissing } from "../logs";
import { seedSource } from "../sourceSeed";
import type { Source } from "../../../types/admin";

const FORMATS = [
  { name: "rfc3164", label: "BSD syslog (RFC 3164)", group: "core", pattern: false },
  { name: "jsonl", label: "JSON lines", group: "core", pattern: false },
  { name: "regex", label: "Regular expression", group: "custom", pattern: true },
];

const PREVIEW = {
  files: [{ path: "/var/log/system.log", bytes: 120, modified: "2026-10-12T12:00:00+00:00" }],
  columns: [
    { name: "_file_id", type: "text" },
    { name: "_line_offset", type: "bigint" },
    { name: "_parse_error", type: "text" },
    { name: "process", type: "text" },
    { name: "message", type: "text" },
    { name: "_landed_at", type: "timestamp" },
  ],
  rows: [
    {
      _file_id: "a1",
      _line_offset: 0,
      process: "syslogd",
      message: "ASL Sender Statistics",
      _parse_error: null,
    },
    {
      _file_id: "a1",
      _line_offset: 60,
      process: null,
      message: null,
      _parse_error: "not in the BSD syslog (RFC 3164) form",
    },
  ],
};

function answer(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the source pick list", () => {
  it("offers log files under File", () => {
    expect(SOURCE_TYPES.find((s) => s.value === "logs")).toMatchObject({
      label: "Log files",
      category: "File",
    });
  });
});

describe("logs helpers", () => {
  it("asks for the files, the format, and a pattern for a format of the source's own", () => {
    expect(logsMissing({})).toEqual(["logs_glob", "logs_format"]);
    expect(logsMissing({ logs_glob: "/var/log/x", logs_format: "regex" })).toEqual([
      "logs_pattern",
    ]);
    expect(logsMissing({ logs_glob: "/var/log/x", logs_format: "jsonl" })).toEqual([]);
  });

  it("saves a pattern only with the regular-expression format and reads the mapping back", () => {
    expect(
      logsMapping({ logs_glob: " /var/log/x ", logs_format: "jsonl", logs_pattern: "(?P<a>.)" }),
    ).toEqual({ glob: "/var/log/x", format: "jsonl" });
    const mapping = logsMapping({
      logs_glob: "/var/log/app.log",
      logs_format: "regex",
      logs_pattern: "(?P<level>\\w+) (?P<message>.*)",
      logs_record_start: "",
    });
    expect(mapping).toEqual({
      glob: "/var/log/app.log",
      format: "regex",
      pattern: "(?P<level>\\w+) (?P<message>.*)",
    });
    expect(logsFieldsFromMapping(JSON.stringify(mapping))).toEqual({
      logs_glob: "/var/log/app.log",
      logs_format: "regex",
      logs_pattern: "(?P<level>\\w+) (?P<message>.*)",
      logs_record_start: "",
    });
  });
});

describe("a saved Logs source", () => {
  it("opens its form with the files and format its mapping holds", () => {
    const mapping = { glob: "/var/log/system.log*", format: "rfc3164" };
    const source = {
      id: "syslog",
      type: "logs",
      mappingJson: JSON.stringify(mapping),
    } as unknown as Source;
    expect(seedSource(source, null).authFields).toMatchObject({
      logs_glob: "/var/log/system.log*",
      logs_format: "rfc3164",
    });
  });
});

describe("LogsFields", () => {
  it("asks for a pattern only for a format of the source's own", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => answer({ formats: FORMATS })),
    );
    const { rerender } = renderInForm(
      <LogsFields fields={{ logs_format: "jsonl" }} setFields={vi.fn()} />,
    );
    expect(screen.getByTestId("logs-glob")).toBeInTheDocument();
    expect(screen.queryByTestId("logs-pattern")).not.toBeInTheDocument();
    rerender(<LogsFields fields={{ logs_format: "regex" }} setFields={vi.fn()} />);
    expect(screen.getByTestId("logs-pattern")).toBeInTheDocument();
    expect(screen.getByTestId("logs-record-start")).toBeInTheDocument();
  });

  it("shows the files, the format's columns and the first rows, a parse error among them", async () => {
    const fetchMock = vi.fn((url: string) =>
      url.endsWith("/formats") ? answer({ formats: FORMATS }) : answer(PREVIEW),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderInForm(
      <LogsFields
        fields={{ logs_glob: "/var/log/system.log*", logs_format: "rfc3164" }}
        setFields={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("logs-preview"));
    const result = await screen.findByTestId("logs-preview-result");
    expect(result).toHaveTextContent("/var/log/system.log");
    expect(result).toHaveTextContent("process text, message text");
    expect(result).not.toHaveTextContent("_file_id text");
    expect(screen.getByTestId("logs-preview-rows")).toHaveTextContent("ASL Sender Statistics");
    expect(screen.getByTestId("logs-preview-rows")).toHaveTextContent("not in the BSD syslog");
    const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith("/preview")) as unknown as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(init.body as string)).toEqual({
      mapping: { glob: "/var/log/system.log*", format: "rfc3164" },
    });
  });

  it("says why the files may not be read", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/formats")
          ? answer({ formats: FORMATS })
          : answer(
              {
                detail:
                  "/etc/*.log resolves to /etc, outside the directories log files may be read from: /var/log",
                code: "logs.path_refused",
                params: { reason: "/etc/*.log resolves to /etc" },
              },
              403,
            ),
      ),
    );
    renderInForm(
      <LogsFields
        fields={{ logs_glob: "/etc/*.log", logs_format: "rfc3164" }}
        setFields={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("logs-preview"));
    await waitFor(() =>
      expect(screen.getByTestId("logs-preview-error")).toHaveTextContent(
        "/etc/*.log resolves to /etc",
      ),
    );
  });

  it("cannot preview before the files and their format are named", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => answer({ formats: FORMATS })),
    );
    renderInForm(<LogsFields fields={{ logs_glob: "/var/log/x" }} setFields={vi.fn()} />);
    expect(screen.getByTestId("logs-preview")).toBeDisabled();
  });
});
