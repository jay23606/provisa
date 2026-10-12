// Copyright (c) 2026 Kenneth Stott
// Canary: 2b7f4c18-5e3a-4d96-91c0-a8e6d3b2f047
//
// This source code is licensed under the Business Source License 1.1
// found in the LICENSE file in the root directory of this source tree.
//
// NOTICE: Use of this software for training artificial intelligence or
// machine learning models is strictly prohibited without explicit written
// permission from the copyright holder.

/**
 * REQ-1992: the org's file folder is encrypted under a key named by a vault reference. A generated
 * key is shown once, with the warning; the key itself is never what is saved.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "../test-utils/render";
import userEvent from "@testing-library/user-event";
import { OrgFilesTab } from "../components/admin/OrgFilesTab";

vi.mock("../api/admin", () => ({
  fetchOrgFiles: vi.fn(),
  setOrgFiles: vi.fn(),
  generateOrgFilesKey: vi.fn(),
}));

import { fetchOrgFiles, generateOrgFilesKey, setOrgFiles } from "../api/admin";
const mockFetch = vi.mocked(fetchOrgFiles);
const mockSet = vi.mocked(setOrgFiles);
const mockGenerate = vi.mocked(generateOrgFilesKey);

beforeEach(() => {
  vi.clearAllMocks();
  mockFetch.mockResolvedValue({ org_id: "acme", encrypted: false, key_reference: null });
});

describe("OrgFilesTab", () => {
  it("shows no warning until a key is generated or named", async () => {
    render(<OrgFilesTab />);
    await screen.findByTestId("org-files");
    expect(screen.queryByTestId("org-files-warning")).toBeNull();
  });

  it("shows a generated key once, with the warning, and never saves it", async () => {
    const user = userEvent.setup();
    mockGenerate.mockResolvedValue("a-new-key");
    render(<OrgFilesTab />);
    await user.click(await screen.findByTestId("org-files-generate"));
    expect(await screen.findByTestId("org-files-generated-key")).toHaveTextContent("a-new-key");
    expect(screen.getByTestId("org-files-warning")).toHaveTextContent(/cannot recover this key/);
    expect(mockSet).not.toHaveBeenCalled();
  });

  it("names the key by a vault reference and refuses a key typed in its place", async () => {
    const user = userEvent.setup();
    mockSet.mockResolvedValue({ org_id: "acme", encrypted: true, key_reference: "${secret:k}" });
    render(<OrgFilesTab />);
    await user.click(await screen.findByTestId("org-files-encrypt"));
    const reference = screen.getByTestId("org-files-reference");
    await user.type(reference, "raw-key-value");
    expect(screen.getByTestId("org-files-save")).toBeDisabled();
    await user.clear(reference);
    await user.type(reference, "${{secret:k}");
    expect(screen.getByTestId("org-files-warning")).toBeInTheDocument();
    await user.click(screen.getByTestId("org-files-save"));
    await waitFor(() =>
      expect(mockSet).toHaveBeenCalledWith({ encrypted: true, key_reference: "${secret:k}" }),
    );
  });

  it("will not encrypt without a reference", async () => {
    const user = userEvent.setup();
    render(<OrgFilesTab />);
    await user.click(await screen.findByTestId("org-files-encrypt"));
    expect(screen.getByTestId("org-files-save")).toBeDisabled();
  });
});
