/**
 * E2E smoke (PLAN §13, Phase 4/5): chat → PR → inbox; approve a consolidated PO; override needs a
 * comment and is audited; amendment via the structured editor → impact → approve → re-run → compare.
 * Runs against a freshly seeded app (BASE_URL, default http://localhost:8000).
 */
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const SAMPLE = path.resolve(__dirname, "../../data/kit/pr_batches/sample_pr_batch.csv");

async function as(page: Page, user: string) {
  await page.goto("/");
  await page.evaluate((u) => {
    localStorage.setItem("corvo.user", u);
    localStorage.setItem("corvo.welcome", "done");
  }, user);
}

test("requester raises the brief's PR in chat in three turns", async ({ page }) => {
  await as(page, "Asha");
  await page.goto("/chat");
  const input = page.getByPlaceholder("e.g. need 200 nitrile gloves");
  await input.fill("need 200 nitrile gloves for Chakan by next Friday");
  await input.press("Enter");
  await expect(page.getByText("ITM-1048 Nitrile coated gloves").first()).toBeVisible();
  await page.getByRole("button", { name: "Normal", exact: true }).click();
  await expect(page.getByText("Shall I raise it?")).toBeVisible();
  await expect(page.getByText("Live preview from the policy engine")).toBeVisible();
  await page.getByRole("button", { name: "Confirm & raise PR" }).click();
  await expect(page.getByText(/Done! PR \*?\*?PR-\d\d-C\d{4}/).first()).toBeVisible();
  await page.getByRole("link", { name: "Open in the buyer inbox" }).click();
  await expect(page.getByText("live PRs from chat")).toBeVisible();
});

test("buyer approves a consolidated PO and overrides with a mandatory comment", async ({ page }) => {
  await as(page, "Rahul");
  await page.goto("/inbox?run=1");
  const consolidated = page.locator('[data-testid="po-card"][data-consolidated="true"]').first();
  await consolidated.getByRole("button", { name: "Approve PO" }).click();
  await expect(page.getByRole("button", { name: /^Done\s*2/ })).toBeVisible();

  await page.getByText("Sourcing to launch").click();
  await page.getByRole("button", { name: /Review next/ }).click();
  await page.getByRole("button", { name: "Override…" }).click();
  const save = page.getByRole("button", { name: "Save override" });
  await expect(save).toBeDisabled();
  const supplierSelect = page.getByLabel("Route");
  await supplierSelect.selectOption("RFP");
  await page.getByPlaceholder("Why is the policy outcome not right here?").fill("Volume justifies a formal RFP");
  await save.click();
  await expect(page.getByText("“Volume justifies a formal RFP”")).toBeVisible();

  await page.goto("/audit");
  await expect(page.getByText("requirement.override").first()).toBeVisible();
});

test("procurement amends the policy in the editor, approves, re-runs and compares", async ({ page }) => {
  await as(page, "Meera");
  await page.goto("/policy/amendments/new");
  await page.getByRole("button", { name: /Structured editor/ }).click();
  await page.locator("select").first().selectOption("set_param");
  await page.locator("select").nth(1).selectOption("spot_limit");
  await page.getByPlaceholder("e.g. 300000").fill("300000");
  await page.getByRole("button", { name: "Add change" }).click();
  await page.locator('input[type="date"]').fill("2026-11-10");
  await page.getByRole("button", { name: "Review changes & impact" }).click();

  await expect(page.getByText("Spot PO limit (spot_limit, clause 5.4): ₹2,00,000 → ₹3,00,000").first()).toBeVisible();
  await expect(page.getByText(/RFQ → SPOT_PO: \d+/)).toBeVisible();
  await page.getByRole("button", { name: /Approve & activate from/ }).click();
  await expect(page.getByText(/is active from/)).toBeVisible();

  await page.goto("/batches");
  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  await page.getByLabel("Run name").fill("Run 2 (e2e)");
  await page.getByRole("button", { name: "Process batch" }).click();
  await expect(page.getByRole("heading", { name: "Run 2 (e2e)" })).toBeVisible();
  await expect(page.getByText("No Blocked/Inactive supplier in any PO or suggestion")).toBeVisible();

  await page.getByRole("button", { name: "Compare" }).click();
  await page.locator("select").first().selectOption("1");
  await expect(page.getByText(/RFQ → SPOT_PO/).first()).toBeVisible();
});
