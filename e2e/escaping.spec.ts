/**
 * Nothing typed into this tool, and nothing a model writes about it, may run as
 * script in the operator's browser.
 *
 * That browser drives the projector. There is no authentication on the API and
 * event mode binds 0.0.0.0, so a payload can arrive from anyone on the network
 * as well as from the keyboard. Every one of these payloads executed before the
 * escaping went in.
 */
import { test, expect, Page } from "@playwright/test";

const PAYLOAD = `<img src=x onerror="window.__XSS=1">`;

async function nothingRan(page: Page) {
  return page.evaluate(() => (window as any).__XSS === undefined);
}

test.describe("Untrusted text never executes", () => {
  test("an event name is text, not markup", async ({ page, request }) => {
    await request.post("/api/events", { data: { name: `${PAYLOAD}Evil Event` } });
    await page.goto("/");
    await page.waitForTimeout(800);

    expect(await nothingRan(page)).toBe(true);
    expect(await page.locator("#event-select img").count()).toBe(0);
    // The name still reaches the operator, just inertly.
    await expect(page.locator("#event-select")).toContainText("Evil Event");
  });

  test("a team name is text, not markup", async ({ page, request }) => {
    const ev = await (await request.post("/api/events", { data: { name: "Escaping" } })).json();
    await request.post("/api/submissions", {
      data: { team_name: `${PAYLOAD}Evil Team`, event_id: ev.id },
    });
    await page.goto("/");
    await page.selectOption("#event-select", ev.id);
    await page.locator('nav .btn:has-text("Submissions")').click();
    await page.waitForTimeout(800);

    expect(await nothingRan(page)).toBe(true);
    expect(await page.locator("#submissions-list img").count()).toBe(0);
    await expect(page.locator("#submissions-list")).toContainText("Evil Team");
  });

  test("a quote in a team name cannot break out of the delete handler", async ({ page, request }) => {
    // The delete button passes the name into an inline onclick. A raw double
    // quote would close the attribute.
    const ev = await (await request.post("/api/events", { data: { name: "Quoting" } })).json();
    await request.post("/api/submissions", {
      data: { team_name: `He said "hi" & <b>left</b>`, event_id: ev.id },
    });
    await page.goto("/");
    await page.selectOption("#event-select", ev.id);
    await page.locator('nav .btn:has-text("Submissions")').click();
    await page.waitForTimeout(800);

    expect(await nothingRan(page)).toBe(true);
    expect(await page.locator("#submissions-list b").count()).toBe(0);
    // And the button is still wired up rather than mangled into nothing.
    await expect(page.locator('#submissions-list button:has-text("Delete")')).toHaveCount(1);
  });
});

test.describe("Deleting", () => {
  async function judgedTeam(request: any, eventName: string, teamName: string) {
    const ev = await (await request.post("/api/events", { data: { name: eventName } })).json();
    const sub = await (await request.post("/api/submissions", {
      data: { team_name: teamName, event_id: ev.id },
    })).json();
    await request.post(`/api/submissions/${sub.id}/audio`, {
      multipart: { file: { name: "p.mp3", mimeType: "audio/mpeg", buffer: Buffer.alloc(4096, 7) } },
    });
    await request.post(`/api/submissions/${sub.id}/judge`);
    return { ev, sub };
  }

  test("a submission can be removed after it has been judged", async ({ page, request }) => {
    const { ev, sub } = await judgedTeam(request, "Delete Sub", "Misfire");

    await page.goto("/");
    await page.selectOption("#event-select", ev.id);
    await page.locator('nav .btn:has-text("Submissions")').click();
    await expect(page.locator("#submissions-list")).toContainText("Misfire");

    page.once("dialog", (d) => d.accept());
    await page.locator('#submissions-list button:has-text("Delete")').first().click();
    await expect(page.locator("#submissions-list")).not.toContainText("Misfire");

    expect((await request.get(`/api/submissions/${sub.id}`)).status()).toBe(404);
  });

  test("cancelling the confirm keeps the submission", async ({ page, request }) => {
    const { ev } = await judgedTeam(request, "Keep Sub", "Survivor");

    await page.goto("/");
    await page.selectOption("#event-select", ev.id);
    await page.locator('nav .btn:has-text("Submissions")').click();

    page.once("dialog", (d) => d.dismiss());
    await page.locator('#submissions-list button:has-text("Delete")').first().click();
    await page.waitForTimeout(500);
    await expect(page.locator("#submissions-list")).toContainText("Survivor");
  });

  test("deleting an event takes its submissions with it", async ({ page, request }) => {
    const { ev, sub } = await judgedTeam(request, "Doomed Event", "Passenger");

    await page.goto("/");
    await page.selectOption("#event-select", ev.id);
    await expect(page.locator("#btn-delete-event")).toBeVisible();

    page.once("dialog", (d) => d.accept());
    await page.locator("#btn-delete-event").click();
    await expect(page.locator("#main-content")).toHaveClass(/hidden/);

    expect((await request.get(`/api/events/${ev.id}`)).status()).toBe(404);
    expect((await request.get(`/api/submissions/${sub.id}`)).status()).toBe(404);
  });

  test("the delete control is hidden until an event is chosen", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#btn-delete-event")).toBeHidden();
  });
});
