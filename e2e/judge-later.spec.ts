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

type RecordOptions = { recordOnly?: boolean; expectFailure?: boolean };

async function record(page: Page, team: string, opts: RecordOptions = {}) {
  await page.fill("#team-name", team);
  if (opts.recordOnly) await page.locator("#record-only").check();
  await page.locator("#btn-start").click();
  await expect(page.locator("#btn-stop")).toBeVisible();
  await page.waitForTimeout(600);
  await page.locator("#btn-stop").click();

  // Judging runs after Stop and takes a moment. Returning before it finishes
  // meant the caller looked at the submissions list mid-pipeline, saw no
  // review, and got a Judge button where it expected Re-judge.
  if (!opts.recordOnly && !opts.expectFailure) {
    await expect(page.locator("#results-panel")).toBeVisible({ timeout: 30_000 });
  }
}

/** Wait for the server to agree the pipeline finished, not just the UI. */
async function awaitJudged(request: any, eventId: string, team: string) {
  await expect
    .poll(async () => {
      const subs = await (await request.get(`/api/events/${eventId}/submissions`)).json();
      return subs.find((s: any) => s.team_name === team)?.status;
    }, { timeout: 30_000 })
    .toBe("complete");
}

test("record-only keeps the pitch and skips the wait", async ({ page, request }) => {
  const ev = await newEvent(request, "Known Outage");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);

  await record(page, "Deferred Team", { recordOnly: true });
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

  await record(page, "Unlucky Team", { expectFailure: true });
  await expect(page.locator("#status")).toContainText("provider is down");
  await expect(page.locator("#status")).toContainText("recording is saved");
});

test("the backlog is visible and clears in one action", async ({ page, request }) => {
  const ev = await newEvent(request, "Backlog");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);

  await record(page, "Waiting One", { recordOnly: true });
  await record(page, "Waiting Two", { recordOnly: true });

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
  await record(page, "Solo Team", { recordOnly: true });

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

test("a judged team can be re-judged from the submissions tab", async ({ page, request }) => {
  // A score that came out wrong, a review whose audio failed, a rubric changed
  // after the fact. The pipeline always supported re-running; nothing in the UI
  // reached it, so the only route was deleting the team and losing the pitch.
  const ev = await newEvent(request, "Second Look");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);
  await record(page, "Reconsidered");

  await page.locator('nav .btn:has-text("Submissions")').click();
  await expect(page.locator("#submissions-list")).toContainText("Reconsidered");

  const rejudge = page.locator('#submissions-list button:has-text("Re-judge")');
  await expect(rejudge).toHaveCount(1);

  const before = await (await request.get(`/api/events/${ev.id}/submissions`)).json();

  page.once("dialog", (d) => d.accept());
  await rejudge.click();

  // The pipeline runs again. Wait for the server, not for the button.
  await awaitJudged(request, ev.id, "Reconsidered");

  const after = await (await request.get(`/api/events/${ev.id}/submissions`)).json();
  expect(after[0].review).toBeTruthy();
  // Replaced, not appended. R31.
  expect(after[0].scores.length).toBe(before[0].scores.length);
});

test("cancelling the confirm leaves the review alone", async ({ page, request }) => {
  const ev = await newEvent(request, "Thought Better");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);
  await record(page, "Untouched");

  await page.locator('nav .btn:has-text("Submissions")').click();
  const before = await (await request.get(`/api/events/${ev.id}/submissions`)).json();

  page.once("dialog", (d) => d.dismiss());
  await page.locator('#submissions-list button:has-text("Re-judge")').click();
  await page.waitForTimeout(800);

  const after = await (await request.get(`/api/events/${ev.id}/submissions`)).json();
  expect(after[0].review.overall_score).toBe(before[0].review.overall_score);
});

test("a team that was never judged offers Judge, not Re-judge", async ({ page, request }) => {
  const ev = await newEvent(request, "Never Judged");
  await page.goto("/");
  await page.selectOption("#event-select", ev.id);
  await record(page, "Waiting", { recordOnly: true });

  await page.locator('nav .btn:has-text("Submissions")').click();
  await expect(page.locator('#submissions-list button:has-text("Re-judge")')).toHaveCount(0);
  await expect(page.locator('#submissions-list button:has-text("Judge")')).toHaveCount(1);
});
