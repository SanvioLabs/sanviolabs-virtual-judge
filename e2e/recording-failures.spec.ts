/**
 * What happens when the recording path goes wrong.
 *
 * Every one of these used to leave the operator stuck: a hidden Start button,
 * a status line frozen on "Uploading audio...", or a misleading error naming
 * the wrong cause. There is a team standing at the microphone when this
 * happens, so the UI has to say what broke and let them try again.
 */
import { test, expect, Page } from "@playwright/test";

async function newEvent(request: any, name: string) {
  return (await request.post("/api/events", { data: { name } })).json();
}

async function readyToRecord(page: Page, eventId: string, team: string) {
  await page.goto("/");
  await page.selectOption("#event-select", eventId);
  await page.fill("#team-name", team);
}

test("a refused microphone says so and lets you retry", async ({ page, request }) => {
  const ev = await newEvent(request, "Mic Denied");
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      const e = new Error("Permission denied");
      e.name = "NotAllowedError";
      throw e;
    };
  });
  await readyToRecord(page, ev.id, "Denied Team");
  await page.locator("#btn-start").click();

  await expect(page.locator("#status")).toContainText("Microphone unavailable");
  // Recoverable, not stuck.
  await expect(page.locator("#btn-start")).toBeVisible();
  await expect(page.locator("#team-name")).toBeEnabled();
});

test("a failed start does not leave an empty team behind", async ({ page, request }) => {
  const ev = await newEvent(request, "No Orphans");
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new Error("no device");
    };
  });
  await readyToRecord(page, ev.id, "Ghost Team");
  await page.locator("#btn-start").click();
  await expect(page.locator("#status")).toContainText("Microphone unavailable");

  const subs = await (await request.get(`/api/events/${ev.id}/submissions`)).json();
  expect(subs).toHaveLength(0);
});

test("a rejected upload names the real reason", async ({ page, request }) => {
  const ev = await newEvent(request, "Upload Rejected");
  await readyToRecord(page, ev.id, "Too Big");

  // The upload used to be fired and ignored, so this surfaced later as
  // "No audio uploaded yet" from the judge step.
  await page.route("**/audio", (route) =>
    route.fulfill({
      status: 413,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Recording is larger than 100 MB" }),
    }),
  );

  await page.locator("#btn-start").click();
  await expect(page.locator("#btn-stop")).toBeVisible();
  await page.waitForTimeout(700);
  await page.locator("#btn-stop").click();

  await expect(page.locator("#status")).toContainText("Upload failed");
  await expect(page.locator("#status")).toContainText("larger than 100 MB");
  await expect(page.locator("#btn-start")).toBeVisible();
});

test("a judge failure is reported and recoverable", async ({ page, request }) => {
  const ev = await newEvent(request, "Judge Failed");
  await readyToRecord(page, ev.id, "Unlucky");

  await page.route("**/judge", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Transcription failed: upstream is down" }),
    }),
  );

  await page.locator("#btn-start").click();
  await expect(page.locator("#btn-stop")).toBeVisible();
  await page.waitForTimeout(700);
  await page.locator("#btn-stop").click();

  await expect(page.locator("#status")).toContainText("upstream is down");
  await expect(page.locator("#btn-start")).toBeVisible();
  await expect(page.locator("#team-name")).toBeEnabled();
});

test("a network error during upload does not hang the UI", async ({ page, request }) => {
  const ev = await newEvent(request, "Network Gone");
  await readyToRecord(page, ev.id, "Offline");

  await page.route("**/audio", (route) => route.abort("failed"));

  await page.locator("#btn-start").click();
  await expect(page.locator("#btn-stop")).toBeVisible();
  await page.waitForTimeout(700);
  await page.locator("#btn-stop").click();

  // Previously an unhandled rejection: the status line just stopped here.
  await expect(page.locator("#status")).toContainText("Something went wrong");
  await expect(page.locator("#btn-start")).toBeVisible();
});

test("the recorder asks the browser what it can record", async ({ page, request }) => {
  const ev = await newEvent(request, "Mime Choice");
  await readyToRecord(page, ev.id, "Codec Team");

  // Stand in for Safari, which does not support audio/webm. The hardcoded
  // mimeType used to make the MediaRecorder constructor throw.
  await page.addInitScript(() => {
    (window as any).MediaRecorder.isTypeSupported = (t: string) => t === "audio/mp4";
  });

  await page.locator("#btn-start").click();
  await expect(page.locator("#btn-stop")).toBeVisible();
  await expect(page.locator("#status")).not.toContainText("Microphone unavailable");
});

test("a failed event creation says so instead of half-opening the app", async ({ page }) => {
  await page.goto("/");
  await page.route("**/api/events", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "no rubric loaded" }),
        })
      : route.continue(),
  );

  await page.locator('button:has-text("New Event")').click();
  await page.fill("#new-event-name", "Doomed");
  await page.locator('button:has-text("Create")').click();

  await expect(page.locator("#status")).toContainText("Could not create the event");
  await expect(page.locator("#status")).toContainText("no rubric loaded");
  // Not left half-open against an id that does not exist.
  await expect(page.locator("#main-content")).toHaveClass(/hidden/);
});

test("a failed submissions load reports instead of showing stale teams", async ({ page, request }) => {
  const first = await (await request.post("/api/events", { data: { name: "Real Teams" } })).json();
  await request.post("/api/submissions", { data: { team_name: "Stale Team", event_id: first.id } });

  await page.goto("/");
  await page.selectOption("#event-select", first.id);
  await page.locator('nav .btn:has-text("Submissions")').click();
  await expect(page.locator("#submissions-list")).toContainText("Stale Team");

  // Now make the next load fail. Calling .map on an error object used to throw
  // into nothing and leave the previous list on screen.
  await page.route("**/submissions", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "db gone" }) })
      : route.continue(),
  );
  await page.locator('nav .btn:has-text("Judge")').click();
  await page.locator('nav .btn:has-text("Submissions")').click();

  await expect(page.locator("#submissions-list")).toContainText("Could not load submissions");
  await expect(page.locator("#submissions-list")).not.toContainText("Stale Team");
});
