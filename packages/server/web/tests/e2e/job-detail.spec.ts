import { expect, test } from "@playwright/test";
import { e2eEnv } from "./env";

const jobId = e2eEnv.E2E_JOB_ID;

test.describe("Job detail e2e", () => {
  test.skip(!jobId, "Set E2E_JOB_ID to run e2e job tests");

  test("timeline panel renders task rows and tabs", async ({ page }) => {
    await page.goto(`/jobs/${jobId}`);

    await expect(page.getByText("Execution Timeline")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Task Runs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Artifacts" })).toBeVisible();

    // Timeline rows are rendered as buttons in the panel.
    const timelineButtons = page.locator("text=Execution Timeline").locator("..").locator("button");
    await expect(timelineButtons.first()).toBeVisible();
  });

  test("artifacts tab supports refresh and can surface expected artifact", async ({ page }) => {
    await page.goto(`/jobs/${jobId}`);

    await page.getByRole("tab", { name: "Artifacts" }).click();
    const refresh = page.getByRole("button", { name: "Refresh artifacts" });
    await expect(refresh).toBeVisible();
    await refresh.click();

    const expectedArtifact = e2eEnv.E2E_EXPECT_ARTIFACT;
    if (expectedArtifact) {
      await expect(page.getByText(expectedArtifact)).toBeVisible();
    }
  });

  test("page remains coherent across network disconnect/reconnect boundaries", async ({ page }) => {
    await page.goto(`/jobs/${jobId}`);
    await expect(page.getByText("Execution Timeline")).toBeVisible();

    // Simulate a transient network outage and recovery.
    await page.context().setOffline(true);
    await page.waitForTimeout(300);
    await page.context().setOffline(false);

    await expect(page.getByText("Execution Timeline")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Logs" })).toBeVisible();
  });
});
