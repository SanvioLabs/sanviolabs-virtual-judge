/**
 * The How to use modal.
 *
 * This is the one piece of UI aimed at someone who has never run the tool, and
 * it is reachable before an event exists, so the tests start from a cold page
 * with nothing selected.
 */
import { test, expect } from "@playwright/test";

test.describe("How to use", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("the button is there before an event is selected", async ({ page }) => {
    // The rest of the UI is hidden until an event exists. Help must not be.
    await expect(page.locator("#main-content")).toHaveClass(/hidden/);
    await expect(page.locator("#btn-howto")).toBeVisible();
  });

  test("clicking it opens the modal", async ({ page }) => {
    await expect(page.locator("#howto-overlay")).toBeHidden();
    await page.locator("#btn-howto").click();
    await expect(page.locator("#howto-overlay")).toBeVisible();
    await expect(page.locator("#howto-title")).toContainText("How to use Virtual Judge");
  });

  test("it covers the whole run, not just recording", async ({ page }) => {
    await page.locator("#btn-howto").click();
    const body = page.locator(".modal-body");
    for (const heading of [
      "Before the first team",
      "For each team",
      "Once everyone has pitched",
      "After the room clears",
    ]) {
      await expect(body).toContainText(heading);
    }
    // The two failure modes worth warning about explicitly.
    await expect(body).toContainText("Do not run PRFAQs between teams");
    await expect(body).toContainText("USB mic");
  });

  test("the close button closes it", async ({ page }) => {
    await page.locator("#btn-howto").click();
    await page.locator("#howto-close").click();
    await expect(page.locator("#howto-overlay")).toBeHidden();
  });

  test("escape closes it", async ({ page }) => {
    await page.locator("#btn-howto").click();
    await page.keyboard.press("Escape");
    await expect(page.locator("#howto-overlay")).toBeHidden();
  });

  test("clicking the backdrop closes it", async ({ page }) => {
    await page.locator("#btn-howto").click();
    // Top-left corner of the overlay is backdrop, never the panel.
    await page.locator("#howto-overlay").click({ position: { x: 5, y: 5 } });
    await expect(page.locator("#howto-overlay")).toBeHidden();
  });

  test("clicking inside the panel does not close it", async ({ page }) => {
    // The regression this guards: a click bubbling to the overlay shuts the
    // help while someone is reading it.
    await page.locator("#btn-howto").click();
    await page.locator("#howto-title").click();
    await expect(page.locator("#howto-overlay")).toBeVisible();
  });

  test("focus moves into the modal and comes back on close", async ({ page }) => {
    await page.locator("#btn-howto").click();
    await expect(page.locator("#howto-close")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.locator("#btn-howto")).toBeFocused();
  });

  test("the page behind cannot scroll while it is open", async ({ page }) => {
    await page.locator("#btn-howto").click();
    await expect(page.locator("body")).toHaveCSS("overflow", "hidden");
    await page.locator("#howto-close").click();
    await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
  });
});
