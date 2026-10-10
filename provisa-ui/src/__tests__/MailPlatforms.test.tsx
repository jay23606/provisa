// Copyright (c) 2026 Kenneth Stott
// Canary: 06d39d81-232a-4535-a09f-1267d092bd84
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

// REQ-1576, REQ-1923: Admin › Email holds the mail Provisa sends (the deployment's) and the mail
// platforms the organisation's sources connect to (the organisation's), under two headings, each
// shown only to a holder of its own right. The platform section takes a client once, shows the
// address to register ready to copy, and never shows a secret back.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "../test-utils/render";
import en from "../i18n/locales/en/mailPlatforms.json";

const auth = vi.hoisted(() => ({
  capabilities: [] as string[],
  activeOrgId: "acme" as string | null,
}));
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../components/admin/MailTab", () => ({
  MailTab: () => <div data-testid="outgoing-mail-form" />,
}));
vi.mock("../api/mailPlatforms", () => ({
  fetchMailPlatforms: vi.fn(),
  putMailPlatform: vi.fn(),
  deleteMailPlatform: vi.fn(),
}));

import { deleteMailPlatform, fetchMailPlatforms, putMailPlatform } from "../api/mailPlatforms";
import { EmailTab } from "../components/admin/EmailTab";
import { MailPlatformsSection } from "../components/admin/MailPlatformsSection";
import { platformMissing } from "../components/admin/mailPlatformDraft";
import { NAV_GROUPS } from "../components/navGroups";

const list = vi.mocked(fetchMailPlatforms);
const put = vi.mocked(putMailPlatform);
const remove = vi.mocked(deleteMailPlatform);

const REDIRECT = "http://localhost:3000/source-sign-in.html";
// An entry that holds a client holds its secret as entered, and the form is handed it.
const KEPT = "client-secret-as-entered";
const google = (over: Record<string, unknown> = {}) => ({
  platform: "google_workspace",
  settings_fields: [] as string[],
  configured: false,
  client_id: null as string | null,
  settings: {} as Record<string, string>,
  organisation_mailboxes: false,
  organisation_settings_fields: [] as string[],
  organisation_key_field: false,
  organisation_key: null as string | null,
  organisation_scopes: [] as string[],
  ...over,
  client_secret: (over.client_secret ?? (over.client_id ? KEPT : null)) as string | null,
});
const tid = (suffix: string) => `mail-platform-google_workspace${suffix}`;

beforeEach(() => {
  auth.capabilities = ["org_settings"];
  auth.activeOrgId = "acme";
  list.mockReset().mockResolvedValue({ redirect_address: REDIRECT, platforms: [google()] });
  put.mockReset().mockResolvedValue(google({ configured: true, client_id: "client-1" }));
  remove.mockReset().mockResolvedValue(undefined);
});

describe("Admin › Email", () => {
  it("shows an organisation administrator the mail platforms and not the mail Provisa sends", async () => {
    render(<EmailTab />);
    expect(await screen.findByTestId("email-mail-platforms")).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.platformsTitle)).toBeInTheDocument();
    expect(screen.queryByTestId("email-outgoing")).toBeNull();
    expect(screen.queryByTestId("outgoing-mail-form")).toBeNull();
  });

  it("shows a platform administrator the mail Provisa sends and not an organisation's platforms", () => {
    auth.capabilities = ["platform_settings"];
    render(<EmailTab />);
    expect(screen.getByTestId("email-outgoing")).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.sentTitle)).toBeInTheDocument();
    expect(screen.queryByTestId("email-mail-platforms")).toBeNull();
    expect(list).not.toHaveBeenCalled();
  });

  it("shows both, each under its own heading and description, to a holder of both rights", async () => {
    auth.capabilities = ["platform_settings", "org_settings"];
    render(<EmailTab />);
    await screen.findByTestId(tid(""));
    expect(screen.getByText(en.mailPlatforms.sentTitle)).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.sentHelp)).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.platformsTitle)).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.platformsHelp)).toBeInTheDocument();
  });

  it("is reached from the menu by either right", () => {
    const entry = NAV_GROUPS.flatMap((g) => g.items).find((i) => i.to === "/admin/email");
    expect(entry).toMatchObject({ capability: "platform_settings", orCapability: "org_settings" });
  });
});

describe("the organisation's mail platforms", () => {
  it("lists Google Workspace as not connected, for the caller's organisation", async () => {
    render(<MailPlatformsSection />);
    expect(await screen.findByTestId(tid("-state"))).toHaveTextContent(
      en.mailPlatforms.notConnected,
    );
    expect(screen.getByText("Google Workspace")).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith("acme");
  });

  it("shows the redirect address ready to copy, with where it goes, and nothing to type", async () => {
    render(<MailPlatformsSection />);
    const address = await screen.findByTestId(tid("-redirect"));
    expect(address).toHaveValue(REDIRECT);
    expect(address).toHaveAttribute("readonly");
    expect(screen.getByTestId(tid("-copy"))).toHaveTextContent(en.mailPlatforms.copy);
    expect(
      screen.getByText(/Google Cloud console, under Authorized redirect URIs/),
    ).toBeInTheDocument();
  });

  it("says which address people must open Provisa at, and that another name will not work", async () => {
    render(<MailPlatformsSection />);
    const note = await screen.findByTestId(tid("-same-address"));
    expect(note).toHaveTextContent("http://localhost:3000");
    expect(note).toHaveTextContent("127.0.0.1 in place of localhost");
  });

  it("says so when the deployment cannot state its address, and still takes the client", async () => {
    list.mockResolvedValue({
      redirect_address: null,
      redirect_problem: "source_sign_in.public_address_not_set",
      platforms: [google()],
    });
    render(<MailPlatformsSection />);
    expect(await screen.findByTestId(tid("-no-redirect"))).toHaveTextContent(
      en.mailPlatforms.redirectUnknown,
    );
    expect(screen.getByTestId(tid("-client-id"))).toBeInTheDocument();
  });

  it("takes the client once: id and secret, the secret typed as a password", async () => {
    render(<MailPlatformsSection />);
    const save = await screen.findByTestId(tid("-save"));
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByTestId(tid("-client-id")), { target: { value: " client-1 " } });
    expect(save).toBeDisabled();
    const secret = screen.getByTestId(tid("-client-secret"));
    expect(secret).toHaveAttribute("type", "password");
    fireEvent.change(secret, { target: { value: "made-up-secret" } });
    fireEvent.click(save);
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("acme", "google_workspace", {
        client_id: "client-1",
        client_secret: "made-up-secret",
        settings: {},
        organisation_mailboxes: false,
      }),
    );
    expect(await screen.findByTestId(tid("-said"))).toHaveTextContent(en.mailPlatforms.saved);
  });

  it.each(["the-secret-as-typed", "${secret:my_google_client}"])(
    "shows the client's secret field again as it was entered (%s), behind the reveal control",
    async (entered) => {
      list.mockResolvedValue({
        redirect_address: REDIRECT,
        platforms: [google({ configured: true, client_id: "client-1", client_secret: entered })],
      });
      render(<MailPlatformsSection />);
      expect(await screen.findByTestId(tid("-state"))).toHaveTextContent(
        en.mailPlatforms.connected,
      );
      const field = screen.getByTestId(tid("-client-secret"));
      expect(field).toHaveValue(entered);
      expect(field).toHaveAttribute("type", "password");
      // Saved with another field changed, the secret goes back exactly as the field holds it.
      fireEvent.change(screen.getByTestId(tid("-client-id")), { target: { value: "client-2" } });
      fireEvent.click(screen.getByTestId(tid("-save")));
      await waitFor(() =>
        expect(put).toHaveBeenCalledWith("acme", "google_workspace", {
          client_id: "client-2",
          client_secret: entered,
          settings: {},
          organisation_mailboxes: false,
        }),
      );
    },
  );

  it("keeps a value typed over what the field held", async () => {
    list.mockResolvedValue({
      redirect_address: REDIRECT,
      platforms: [
        google({ configured: true, client_id: "client-1", client_secret: "${secret:earlier}" }),
      ],
    });
    render(<MailPlatformsSection />);
    const field = await screen.findByTestId(tid("-client-secret"));
    fireEvent.change(field, { target: { value: "typed-now" } });
    fireEvent.click(screen.getByTestId(tid("-save")));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith(
        "acme",
        "google_workspace",
        expect.objectContaining({ client_secret: "typed-now" }),
      ),
    );
  });

  it("removes a connected platform, and offers no removal of one that is not", async () => {
    render(<MailPlatformsSection />);
    await screen.findByTestId(tid("-save"));
    expect(screen.queryByTestId(tid("-remove"))).toBeNull();
    list.mockResolvedValue({
      redirect_address: REDIRECT,
      platforms: [google({ configured: true, client_id: "client-1" })],
    });
    render(<MailPlatformsSection />);
    fireEvent.click((await screen.findAllByTestId(tid("-remove")))[0]);
    await waitFor(() => expect(remove).toHaveBeenCalledWith("acme", "google_workspace"));
  });

  it("shows a refusal beside the platform it concerns", async () => {
    put.mockRejectedValue(new Error("google_workspace needs client_secret"));
    render(<MailPlatformsSection />);
    fireEvent.change(await screen.findByTestId(tid("-client-id")), { target: { value: "c" } });
    fireEvent.change(screen.getByTestId(tid("-client-secret")), { target: { value: "s" } });
    fireEvent.click(screen.getByTestId(tid("-save")));
    expect(await screen.findByTestId(tid("-said"))).toHaveTextContent("needs client_secret");
  });

  it("shows Microsoft 365 by name with its tenant setting labelled and where its address goes", async () => {
    list.mockResolvedValue({
      redirect_address: REDIRECT,
      platforms: [google({ platform: "microsoft_365", settings_fields: ["tenant"] })],
    });
    render(<MailPlatformsSection />);
    expect(await screen.findByText("Microsoft 365")).toBeInTheDocument();
    expect(screen.getByTestId("mail-platform-microsoft_365-setting-tenant")).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.setting.tenant)).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.settingHelp.tenant)).toBeInTheDocument();
    expect(screen.getByText(en.mailPlatforms.redirectHelp.microsoft_365)).toBeInTheDocument();
  });

  it("has a switch, off until an administrator turns it on, for reading the organisation's mailboxes", async () => {
    list.mockResolvedValue({
      redirect_address: REDIRECT,
      platforms: [google({ configured: true, client_id: "client-1" })],
    });
    render(<MailPlatformsSection />);
    const allow = await screen.findByTestId(tid("-organisation-mailboxes"));
    expect(allow).not.toBeChecked();
    expect(screen.getByText(en.mailPlatforms.organisationMailboxes)).toBeInTheDocument();
    fireEvent.click(allow);
    expect(put).not.toHaveBeenCalled(); // saved with the entry, not on the click
    fireEvent.click(screen.getByTestId(tid("-save")));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("acme", "google_workspace", {
        client_id: "client-1",
        client_secret: KEPT,
        settings: {},
        organisation_mailboxes: true,
      }),
    );
  });

  it("says what the administrator grants at Microsoft for it, and nothing for a platform with no wording", async () => {
    list.mockResolvedValue({
      redirect_address: REDIRECT,
      platforms: [
        google({ platform: "another_platform" }),
        google({ platform: "microsoft_365", settings_fields: ["tenant"] }),
      ],
    });
    render(<MailPlatformsSection />);
    expect(
      await screen.findByTestId("mail-platform-microsoft_365-organisation-grant"),
    ).toHaveTextContent("Mail.Read and User.Read.All");
    expect(screen.queryByTestId("mail-platform-another_platform-organisation-grant")).toBeNull();
  });

  describe("Google Workspace's own credential for the organisation's mailboxes", () => {
    const SCOPES = [
      "https://www.googleapis.com/auth/gmail.readonly",
      "https://www.googleapis.com/auth/admin.directory.user.readonly",
      "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
    ];
    const workspace = (over = {}) =>
      google({
        configured: true,
        client_id: "client-1",
        organisation_settings_fields: ["admin_address"],
        organisation_key_field: true,
        organisation_scopes: SCOPES,
        ...over,
      });
    const KEY = '{"made-up": "service account key"}';

    it("asks for the key as a text field and the administrator address, and says what to authorise", async () => {
      list.mockResolvedValue({ redirect_address: REDIRECT, platforms: [workspace()] });
      render(<MailPlatformsSection />);
      const key = await screen.findByTestId(tid("-organisation-key"));
      // What was typed, never a file chosen: a reference or the key's JSON.
      expect(key).toHaveAttribute("type", "password");
      expect(document.querySelector('input[type="file"]')).toBeNull();
      expect(screen.getByText(en.mailPlatforms.setting.admin_address)).toBeInTheDocument();
      expect(screen.getByText(en.mailPlatforms.organisationKeyHelp)).toBeInTheDocument();
      expect(screen.getByTestId(tid("-organisation-scopes"))).toHaveValue(SCOPES.join(","));
      expect(screen.getByTestId(tid("-organisation-scopes-copy"))).toBeInTheDocument();
      const grant = screen.getByTestId(tid("-organisation-grant"));
      expect(grant).toHaveTextContent("Manage Domain Wide Delegation");
      // Said plainly: Google has no way to narrow the delegation.
      expect(grant).toHaveTextContent("Google cannot limit this to some mailboxes");
      expect(grant).toHaveTextContent("covers every user of the domain");
    });

    it("cannot be allowed before the key and the administrator address are given", () => {
      const on = {
        client_id: "c",
        client_secret: "s",
        settings: { admin_address: "" },
        organisation_mailboxes: true,
        organisation_key: "",
      };
      expect(platformMissing(workspace(), on)).toEqual(["admin_address", "organisation_key"]);
      expect(platformMissing(workspace(), { ...on, organisation_mailboxes: false })).toEqual([]);
      const given = { ...on, settings: { admin_address: "admin@example.test" } };
      expect(platformMissing(workspace(), { ...given, organisation_key: KEY })).toEqual([]);
    });

    it("needs no client once such sources are allowed, and half a client is still refused", () => {
      const none = {
        client_id: "",
        client_secret: "",
        settings: { admin_address: "admin@example.test" },
        organisation_mailboxes: true,
        organisation_key: KEY,
      };
      const fresh = workspace({ configured: false, client_id: null });
      expect(platformMissing(fresh, none)).toEqual([]);
      expect(platformMissing(fresh, { ...none, client_id: "c" })).toEqual(["client_secret"]);
      expect(platformMissing(fresh, { ...none, client_secret: "s" })).toEqual(["client_id"]);
      // Only with such sources allowed: otherwise nothing could read with the entry.
      expect(platformMissing(fresh, { ...none, organisation_mailboxes: false })).toEqual([
        "client_id",
        "client_secret",
      ]);
      // An entry kept with no client holds no secret to keep.
      const kept = workspace({ client_id: null, organisation_key: KEY });
      expect(platformMissing(kept, { ...none, client_id: "c" })).toEqual(["client_secret"]);
      // A platform whose credential is its client always needs it.
      expect(platformMissing(google({ configured: false, client_id: null }), none)).toEqual([
        "client_id",
        "client_secret",
      ]);
    });

    it("says the client is only for one person's sign-in", async () => {
      list.mockResolvedValue({ redirect_address: REDIRECT, platforms: [workspace()] });
      render(<MailPlatformsSection />);
      expect(await screen.findByText(en.mailPlatforms.clientOptional)).toBeInTheDocument();
    });

    it("sends the key as it was typed", async () => {
      list.mockResolvedValue({ redirect_address: REDIRECT, platforms: [workspace()] });
      render(<MailPlatformsSection />);
      fireEvent.change(await screen.findByTestId(tid("-organisation-key")), {
        target: { value: "${secret:my_google_key}" },
      });
      fireEvent.change(screen.getByTestId(tid("-setting-admin_address")), {
        target: { value: "admin@example.test" },
      });
      fireEvent.click(screen.getByTestId(tid("-organisation-mailboxes")));
      await waitFor(() => expect(screen.getByTestId(tid("-save"))).toBeEnabled());
      fireEvent.click(screen.getByTestId(tid("-save")));
      await waitFor(() =>
        expect(put).toHaveBeenCalledWith("acme", "google_workspace", {
          client_id: "client-1",
          client_secret: KEPT,
          settings: { admin_address: "admin@example.test" },
          organisation_mailboxes: true,
          organisation_key: "${secret:my_google_key}",
        }),
      );
    });

    it("sends a key file's text pasted into the field as the same JSON", async () => {
      // A key file as Google Cloud writes it: one member a line, the private key's own line
      // breaks escaped inside its string. A one-line field drops the breaks between members.
      const original = {
        type: "service_account",
        project_id: "made-up-project",
        private_key:
          "-----BEGIN PRIVATE KEY-----\nmade-up-line-1\nmade-up-line-2\n-----END PRIVATE KEY-----\n",
        client_email: "reader@made-up-project.iam.gserviceaccount.com",
        token_uri: "https://oauth2.googleapis.com/token",
      };
      const file = JSON.stringify(original, null, 2) + "\n";
      expect(file.split("\n").length).toBeGreaterThan(5);
      list.mockResolvedValue({
        redirect_address: REDIRECT,
        platforms: [
          workspace({
            organisation_mailboxes: true,
            settings: { admin_address: "admin@example.test" },
          }),
        ],
      });
      render(<MailPlatformsSection />);
      const field = await screen.findByTestId(tid("-organisation-key"));
      fireEvent.paste(field, { clipboardData: { getData: () => file } });
      fireEvent.change(field, { target: { value: file } });
      await waitFor(() => expect(screen.getByTestId(tid("-save"))).toBeEnabled());
      fireEvent.click(screen.getByTestId(tid("-save")));
      await waitFor(() => expect(put).toHaveBeenCalled());
      const sent = put.mock.calls[0][2].organisation_key as string;
      // What the input holds is one line, and it parses to the key file's own content.
      expect(sent).not.toContain("\n");
      expect(JSON.parse(sent)).toEqual(original);
    });

    it("shows again what the field holds, and sends it unchanged", async () => {
      list.mockResolvedValue({
        redirect_address: REDIRECT,
        platforms: [
          workspace({
            organisation_key: KEY,
            organisation_mailboxes: true,
            settings: { admin_address: "admin@example.test" },
          }),
        ],
      });
      render(<MailPlatformsSection />);
      expect(await screen.findByTestId(tid("-organisation-key"))).toHaveValue(KEY);
      fireEvent.click(screen.getByTestId(tid("-save")));
      await waitFor(() => expect(put).toHaveBeenCalled());
      expect(put.mock.calls[0][2]).toHaveProperty("organisation_key", KEY);
    });

    it("shows none of it for a platform whose credential is its client", async () => {
      render(<MailPlatformsSection />);
      await screen.findByTestId(tid("-save"));
      expect(screen.queryByTestId(tid("-organisation-key"))).toBeNull();
      expect(screen.queryByTestId(tid("-organisation-scopes"))).toBeNull();
    });
  });

  it("shows the switch as the organisation left it", async () => {
    list.mockResolvedValue({
      redirect_address: REDIRECT,
      platforms: [google({ configured: true, client_id: "c", organisation_mailboxes: true })],
    });
    render(<MailPlatformsSection />);
    expect(await screen.findByTestId(tid("-organisation-mailboxes"))).toBeChecked();
  });

  it("asks for each setting a platform declares, and needs it", () => {
    const tenanted = google({ platform: "tenanted", settings_fields: ["tenant"] });
    const draft = {
      client_id: "c",
      client_secret: "s",
      settings: { tenant: "" },
      organisation_mailboxes: false,
      organisation_key: "",
    };
    expect(platformMissing(tenanted, draft)).toEqual(["tenant"]);
    expect(platformMissing(tenanted, { ...draft, settings: { tenant: "contoso" } })).toEqual([]);
    expect(platformMissing(google(), { ...draft, client_id: "", client_secret: "" })).toEqual([
      "client_id",
      "client_secret",
    ]);
  });
});
