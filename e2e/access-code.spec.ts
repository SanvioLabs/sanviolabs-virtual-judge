/**
 * The access code gate, in the browser.
 *
 * The suite's own server runs without a code, so these drive the gate directly
 * rather than restarting the app: what matters in the browser is that the page
 * loads, the prompt appears when the server says a code is set, a wrong code
 * says so, and a right one gets out of the way.
 */
import { test, expect } from "@playwright/test";

async function serverClaimsACodeIsSet(page: any, sessionStatus = 200) {
  await page.route("**/api/health", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok", access_code_set: true, keys_configured: {},
        models: {}, rubrics_loaded: 1, events_count: 0,
      }),
    }),
  );
  let firstEvents = true;
  await page.route("**/api/events", (route: any) => {
    if (route.request().method() !== "GET") return route.continue();
    if (firstEvents) { firstEvents = false; return route.fulfill({ status: 401, body: "{}" }); }
    return route.continue();
  });
  await page.route("**/api/session", (route: any) =>
    route.fulfill({
      status: sessionStatus,
      contentType: "application/json",
      body: JSON.stringify(sessionStatus === 200 ? { status: "ok" } : { detail: "That code is not right." }),
    }),
  );
}

test("the page still loads when a code is required", async ({ page }) => {
  await serverClaimsACodeIsSet(page);
  await page.goto("/");
  // Otherwise there is nowhere to type it.
  await expect(page.locator("h1")).toContainText("Virtual Judge");
  await expect(page.locator("#access-overlay")).toBeVisible();
});

test("a wrong code says so and lets you retry", async ({ page }) => {
  await serverClaimsACodeIsSet(page, 401);
  await page.goto("/");
  await page.fill("#access-code", "guessing");
  await page.locator('#access-overlay button:has-text("Enter")').click();
  await expect(page.locator("#access-error")).toBeVisible();
  await expect(page.locator("#access-error")).toContainText("not right");
  await expect(page.locator("#access-overlay")).toBeVisible();
});

test("the right code gets out of the way", async ({ page }) => {
  await serverClaimsACodeIsSet(page, 200);
  await page.goto("/");
  await page.fill("#access-code", "letmein");
  await page.locator('#access-overlay button:has-text("Enter")').click();
  await expect(page.locator("#access-overlay")).toBeHidden();
  await expect(page.locator("#event-selector")).toBeVisible();
});

test("no prompt when the server has no code", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#access-overlay")).toBeHidden();
  await expect(page.locator("#event-selector")).toBeVisible();
});
