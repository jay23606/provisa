// Copyright (c) 2026 Kenneth Stott
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1954: ServiceNow is in the source pick list under Enterprise; its form asks for the
// instance's address and a username and password.

import { describe, expect, it, vi } from "vitest";
import { renderInForm, screen } from "../../../test-utils/render";
import { ServiceNowFields } from "../ServiceNowFields";
import { SOURCE_TYPES } from "../constants";
import { servicenowInstanceUrlValid } from "../servicenow";
import { tableGroups } from "../../tables/tableGroups";

const FORM = { host: "https://acme.service-now.com", username: "admin", password: "pw" };

describe("the source pick list", () => {
  it("offers ServiceNow under Enterprise", () => {
    expect(SOURCE_TYPES.find((s) => s.value === "servicenow")).toMatchObject({
      label: "ServiceNow",
      category: "Enterprise",
    });
  });
});

describe("servicenowInstanceUrlValid", () => {
  it("takes the full https address or a reference to it", () => {
    expect(servicenowInstanceUrlValid("https://acme.service-now.com")).toBe(true);
    expect(servicenowInstanceUrlValid("${secret:snow_url}")).toBe(true);
  });

  it("refuses a bare host and any other scheme", () => {
    expect(servicenowInstanceUrlValid("acme.service-now.com")).toBe(false);
    expect(servicenowInstanceUrlValid("http://acme.service-now.com")).toBe(false);
  });
});

describe("ServiceNowFields", () => {
  it("asks for the instance URL, the username and the password", () => {
    renderInForm(<ServiceNowFields form={FORM} setForm={vi.fn()} />);
    expect(screen.getByTestId("servicenow-instance-url-input")).toHaveValue(FORM.host);
    expect(screen.getByTestId("servicenow-username-input")).toHaveValue("admin");
    expect(screen.getByTestId("servicenow-password-input")).toHaveValue("pw");
  });

  it("says an instance URL without https:// is not the full address", () => {
    renderInForm(
      <ServiceNowFields form={{ ...FORM, host: "acme.service-now.com" }} setForm={vi.fn()} />,
    );
    expect(
      screen.getByText("Enter the full instance address, starting with https://"),
    ).toBeInTheDocument();
  });
});

describe("tableGroups", () => {
  it("gathers each table under its heading, in the order the source lists them", () => {
    const tables = [
      { name: "incident", group: "Incident" },
      { name: "change_request", group: "Change Request" },
      { name: "incident_task", group: "Incident" },
    ];
    expect(tableGroups(tables)).toEqual([
      ["Incident", [tables[0], tables[2]]],
      ["Change Request", [tables[1]]],
    ]);
  });

  it("lists tables without a heading first, under none", () => {
    const tables = [{ name: "orders" }, { name: "incident", group: "Incident" }];
    expect(tableGroups(tables)).toEqual([
      [null, [tables[0]]],
      ["Incident", [tables[1]]],
    ]);
  });
});
