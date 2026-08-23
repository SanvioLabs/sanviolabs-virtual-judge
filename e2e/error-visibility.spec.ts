/**
 * SPEC.md R50. Every error the operator can act on is visible on screen.
 *
 * Two ways this was failing. Three loaders reported only to console, so a 500
 * left an empty dropdown and no explanation. And every action on the
 * Submissions tab wrote its error into #status, which lives inside the Judge
 * view: correct markup, invisible message, because the operator is on a
 * different tab when they press those buttons.
 */
import { test, expect, Page } from "@playwright/test";

async function onSubmissions(page: Page, request: any, team = "Visible") {
  const ev = await (await request.post("/api/events", { data: { name: "Errors" } })).json();
  const sub = await (await request.post("/api/submissions", {
    data: { team_name: team, event_id: ev.id },
  })).json();
  await request.post(`/api/submissions/${sub.id}/audio`, {
    multipart: { file: { name: "p.webm", mimeType: "audio/webm", buffer: Buffer.alloc(2048, 5) } },
  });
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);
  await page.locator('nav .btn:has-text("Submissions")').click();
  return { ev, sub };
}

test("a failed judge from the submissions tab is visible there", async ({ page, request }) => {
  await onSubmissions(page, request);
  await page.route("**/judge", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Transcription failed: provider is down" }),
    }),
  );

  await page.locator('#submissions-list button:has-text("Judge")').first().click();
  // Visible, not merely present in the DOM of a hidden tab.
  await expect(page.locator("#app-status")).toBeVisible();
  await expect(page.locator("#app-status")).toContainText("provider is down");
});

test("a failed delete from the submissions tab is visible there", async ({ page, request }) => {
  await onSubmissions(page, request, "Undeletable");
  await page.route("**/api/submissions/*", (route) =>
    route.request().method() === "DELETE"
      ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "database is locked" }) })
      : route.continue(),
  );

  page.once("dialog", (d) => d.accept());
  await page.locator('#submissions-list button:has-text("Delete")').first().click();
  await expect(page.locator("#app-status")).toBeVisible();
  await expect(page.locator("#app-status")).toContainText("database is locked");
});

test("a failed judge-all is visible", async ({ page, request }) => {
  await onSubmissions(page, request, "Backlogged");
  await page.route("**/judge-pending", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "everything is on fire" }) }),
  );

  await page.locator('#pending-banner button:has-text("Judge all")').click();
  await expect(page.locator("#app-status")).toBeVisible();
  await expect(page.locator("#app-status")).toContainText("everything is on fire");
});

test("a failed event list says so instead of showing an empty dropdown", async ({ page }) => {
  await page.route("**/api/events", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ status: 500, contentType: "text/plain", body: "Internal Server Error" })
      : route.continue(),
  );
  await page.goto("/");
  await expect(page.locator("#app-status")).toBeVisible();
  await expect(page.locator("#app-status")).toContainText("Could not load");
});

test("the message can be dismissed", async ({ page, request }) => {
  await onSubmissions(page, request, "Dismissable");
  await page.route("**/judge", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "nope" }) }),
  );
  await page.locator('#submissions-list button:has-text("Judge")').first().click();
  await expect(page.locator("#app-status")).toBeVisible();
  await page.locator("#app-status button").click();
  await expect(page.locator("#app-status")).toBeHidden();
});

test("nothing is shown when nothing is wrong", async ({ page, request }) => {
  await onSubmissions(page, request, "Fine");
  await expect(page.locator("#app-status")).toBeHidden();
});
