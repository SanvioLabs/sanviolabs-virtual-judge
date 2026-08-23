/**
 * Record now, judge later.
 *
 * A provider outage is the only failure in this system that can cost a whole
 * event rather than one team. These cover the operator's path through one:
 * the pitch is kept, the room moves on, and the backlog is cleared when the
 * provider comes back.
 */
import { test, expect, Page } from "@playwright/test";

async function newEvent(request: any, name: string) {
  return (await request.post("/api/events", { data: { name } })).json();
}

async function record(page: Page, team: string, recordOnly = false) {
  await page.fill("#team-name", team);
  if (recordOnly) await page.locator("#record-only").check();
  await page.locator("#btn-start").click();
  await expect(page.locator("#btn-stop")).toBeVisible();
  await page.waitForTimeout(600);
  await page.locator("#btn-stop").click();
}

test("record-only keeps the pitch and skips the wait", async ({ page, request }) => {
  const ev = await newEvent(request, "Known Outage");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);

  await record(page, "Deferred Team", true);
  await expect(page.locator("#status")).toContainText("Recorded");
  await expect(page.locator("#status")).toContainText("Submissions tab");

  const subs = await (await request.get(`/api/events/${ev.id}/submissions`)).json();
  expect(subs).toHaveLength(1);
  expect(subs[0].status).toBe("recorded");
  expect(subs[0].audio_path).toBeTruthy();
  expect(subs[0].review).toBeNull();
});

test("a failed run says the recording is safe", async ({ page, request }) => {
  const ev = await newEvent(request, "Outage Mid Pitch");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);

  await page.route("**/judge", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Transcription failed: provider is down" }),
    }),
  );

  await record(page, "Unlucky Team");
  await expect(page.locator("#status")).toContainText("provider is down");
  await expect(page.locator("#status")).toContainText("recording is saved");
});

test("the backlog is visible and clears in one action", async ({ page, request }) => {
  const ev = await newEvent(request, "Backlog");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);

  await record(page, "Waiting One", true);
  await record(page, "Waiting Two", true);

  await page.locator('nav .btn:has-text("Submissions")').click();
  await expect(page.locator("#pending-banner")).toBeVisible();
  await expect(page.locator("#pending-banner")).toContainText("2 recordings waiting");

  await page.locator('#pending-banner button:has-text("Judge all")').click();
  await expect(page.locator("#pending-banner")).toBeHidden({ timeout: 30_000 });

  const subs = await (await request.get(`/api/events/${ev.id}/submissions`)).json();
  expect(subs.every((s: any) => s.status === "complete")).toBe(true);
  expect(subs.every((s: any) => s.review)).toBeTruthy();
});

test("one team can be judged on its own", async ({ page, request }) => {
  const ev = await newEvent(request, "One At A Time");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);
  await record(page, "Solo Team", true);

  await page.locator('nav .btn:has-text("Submissions")').click();
  await page.locator('#submissions-list button:has-text("Judge")').first().click();

  await expect(page.locator("#submissions-list")).toContainText("Solo Team");
  await expect(page.locator("#pending-banner")).toBeHidden({ timeout: 30_000 });
});

test("no banner when there is nothing waiting", async ({ page, request }) => {
  const ev = await newEvent(request, "All Clear");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);
  await page.locator('nav .btn:has-text("Submissions")').click();
  await expect(page.locator("#pending-banner")).toBeHidden();
});
