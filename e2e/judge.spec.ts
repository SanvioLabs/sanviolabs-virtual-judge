/**
 * Virtual Judge — End-to-End Tests
 *
 * Tests the full user flow using Playwright with mocked external services.
 * Server runs with MOCK_EXTERNALS=true so no API keys are needed.
 *
 * The mock externals return 3 canned GenAI hackathon pitches (~5 min each):
 * - NovaMind (strong): AI-powered clinical documentation
 * - ContextCraft (medium): Cross-tool knowledge graph for dev teams
 * - YOLOship (weak): Music-driven code generation (creative but impractical)
 */
import { test, expect, Page } from "@playwright/test";

// --- Helpers ---

/** Inject a fake MediaStream so getUserMedia returns synthetic audio */
async function injectFakeMediaStream(page: Page) {
  await page.addInitScript(() => {
    // Override getUserMedia before the page's code runs
    const originalGetUserMedia =
      navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);

    navigator.mediaDevices.getUserMedia = async (constraints) => {
      if (constraints && (constraints as MediaStreamConstraints).audio) {
        // Create an AudioContext and a silent oscillator as the stream source
        const ctx = new AudioContext();
        const oscillator = ctx.createOscillator();
        oscillator.frequency.value = 440; // A4 tone
        const dest = ctx.createMediaStreamDestination();
        oscillator.connect(dest);
        oscillator.start();
        return dest.stream;
      }
      return originalGetUserMedia(constraints);
    };
  });
}

/** Create an event and select it */
async function createAndSelectEvent(page: Page, name: string) {
  // Click "New Event"
  await page.click('button:has-text("New Event")');
  await page.fill("#new-event-name", name);
  await page.click('button:has-text("Create")');

  // Wait for it to be selected
  await expect(page.locator("#main-content")).toBeVisible();
}

/** Record and judge a team submission */
async function submitTeam(page: Page, teamName: string) {
  // Fill team name
  await page.fill("#team-name", teamName);

  // Start recording
  await page.click("#btn-start");

  // Verify recording indicator appears
  await expect(page.locator("#recording-indicator")).toHaveClass(/active/, {
    timeout: 10_000,
  });

  // Wait a moment (simulates a brief recording)
  await page.waitForTimeout(1500);

  // Stop recording — triggers upload + judging
  await page.click("#btn-stop");

  // Wait for judging to complete (status should show processing, then results)
  await expect(page.locator("#results-panel")).toBeVisible({ timeout: 60_000 });
}

// --- Tests ---

test.describe("Virtual Judge — Full Flow", () => {
  test.beforeEach(async ({ page }) => {
    await injectFakeMediaStream(page);
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("Virtual Judge");
  });

  test("page loads with title and event selector", async ({ page }) => {
    await expect(page.locator("#event-selector")).toBeVisible();
    await expect(page.locator("#event-select")).toBeVisible();
    await expect(page.locator('button:has-text("New Event")')).toBeVisible();
    // Main content hidden until event is selected
    await expect(page.locator("#main-content")).toBeHidden();
  });

  test("health check passes in mock mode", async ({ page }) => {
    const res = await page.request.get("/api/health");
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    expect(data.status).toBeDefined();
  });

  test("create an event and see nav tabs", async ({ page }) => {
    await createAndSelectEvent(page, "GenAI Builders Hackathon");

    // Nav should be visible with 3 tabs
    await expect(page.locator("nav button:has-text('Judge')")).toBeVisible();
    await expect(page.locator("nav button:has-text('Submissions')")).toBeVisible();
    await expect(page.locator("nav button:has-text('Finalist')")).toBeVisible();
  });

  test("record and judge a single team", async ({ page }) => {
    await createAndSelectEvent(page, "Single Team Test");
    await submitTeam(page, "NovaMind");

    // Verify results displayed
    await expect(page.locator("#results-team")).toContainText("NovaMind");
    await expect(page.locator("#overall-score")).not.toHaveText("-");

    // Score cards should be rendered (4 categories in the rubric)
    const scoreCards = page.locator(".score-card");
    await expect(scoreCards).toHaveCount(4);

    // Summary should be populated
    await expect(page.locator("#review-summary")).not.toBeEmpty();

    // Audio element should have a src
    const audio = page.locator("#review-audio");
    await expect(audio).toHaveAttribute("src", /\/audio\/.*_review\.mp3/);
  });

  test("full 3-team flow with finalist round", async ({ page }) => {
    await createAndSelectEvent(page, "Full Hackathon Flow");

    // --- Submit 3 teams ---

    // Team 1: NovaMind
    await submitTeam(page, "NovaMind");
    await expect(page.locator("#results-team")).toContainText("NovaMind");
    // Click "Next Team" to reset
    await page.click('button:has-text("Next Team")');
    await expect(page.locator("#results-panel")).toBeHidden();

    // Team 2: ContextCraft
    await submitTeam(page, "ContextCraft");
    await expect(page.locator("#results-team")).toContainText("ContextCraft");
    await page.click('button:has-text("Next Team")');

    // Team 3: YOLOship
    await submitTeam(page, "YOLOship");
    await expect(page.locator("#results-team")).toContainText("YOLOship");
    await page.click('button:has-text("Next Team")');

    // --- Check submissions list ---

    await page.click('button:has-text("Submissions")');
    await expect(page.locator("#view-submissions")).toBeVisible();

    // Should show 3 submissions
    const items = page.locator(".submission-item");
    await expect(items).toHaveCount(3);

    // Each should have a score badge
    const badges = page.locator(".score-badge");
    for (let i = 0; i < 3; i++) {
      await expect(badges.nth(i)).not.toHaveText("—");
    }

    // --- Run finalist ---

    await page.click('button:has-text("Finalist")');
    await expect(page.locator("#view-finalist")).toBeVisible();
    await page.click("#btn-finalist");

    // Wait for results
    await expect(page.locator("#finalist-results")).toBeVisible({
      timeout: 30_000,
    });

    // Should show 3 ranked teams
    const finalistCards = page.locator(".finalist-result");
    await expect(finalistCards).toHaveCount(3);

    // First place should be gold
    await expect(finalistCards.first()).toHaveClass(/gold/);

    // Finalist audio should be present
    const finalistAudio = page.locator("#finalist-audio");
    await expect(finalistAudio).toBeVisible();
    await expect(finalistAudio).toHaveAttribute("src", /\/audio\/finalist_/);
  });

  test("cannot start recording without team name", async ({ page }) => {
    await createAndSelectEvent(page, "Validation Test");

    // Try to record with empty name
    await page.click("#btn-start");

    // Should show error status
    await expect(page.locator("#status")).toContainText("Enter a team name");
    await expect(page.locator("#status")).toHaveClass(/error/);
  });

  test("finalist requires 3 completed submissions", async ({ page }) => {
    await createAndSelectEvent(page, "Not Enough Teams");

    // Submit only 1 team
    await submitTeam(page, "OnlyOne");
    await page.click('button:has-text("Next Team")');

    // Try finalist
    await page.click('button:has-text("Finalist")');
    await page.click("#btn-finalist");

    // Should show error
    await expect(page.locator("#finalist-status")).toContainText("at least 3");
    await expect(page.locator("#finalist-status")).toHaveClass(/error/);
  });

  test("submissions view shows scores per category", async ({ page }) => {
    await createAndSelectEvent(page, "Score Display Test");
    await submitTeam(page, "NovaMind");
    await page.click('button:has-text("Next Team")');

    // Go to submissions view
    await page.click('button:has-text("Submissions")');

    // Should have category score badges
    const categoryBadges = page.locator(
      ".submission-item span:has-text('Real-World Impact')"
    );
    await expect(categoryBadges).toBeVisible();
  });

  test("writing a PRFAQ from the submissions view", async ({ page }) => {
    await createAndSelectEvent(page, "PRFAQ UI Test");
    await submitTeam(page, "NovaMind");
    await page.click('button:has-text("Next Team")');
    await page.click('button:has-text("Submissions")');

    // Exact names throughout — "Write PRFAQ" is a substring of "Rewrite PRFAQ",
    // so a loose matcher passes whichever state the row is actually in.
    const writeBtn = page.getByRole("button", { name: "Write PRFAQ", exact: true });
    const viewBtn = page.getByRole("button", { name: "PRFAQ", exact: true });
    const rewriteBtn = page.getByRole("button", { name: "Rewrite PRFAQ", exact: true });

    // Unwritten teams offer to write one, and nothing else
    await expect(writeBtn).toBeVisible();
    await expect(rewriteBtn).toHaveCount(0);
    await writeBtn.click();

    // The ledger is the point of the document — it must render
    const panel = page.locator(".submission-item div[id^='prfaq-']");
    await expect(panel).toContainText("assumptions", { timeout: 60_000 });
    await expect(panel).toContainText("untested");
    await expect(panel).toContainText("Nobody reviewed it");

    // The row relabels itself in place. Waiting for a reload to find out a
    // document exists is how somebody pays for a second one by accident.
    await expect(rewriteBtn).toBeVisible();
    await expect(viewBtn).toBeVisible();
    await expect(writeBtn).toHaveCount(0);

    // And it survives a reload
    await page.click('button:has-text("Judge")');
    await page.click('button:has-text("Submissions")');
    await expect(rewriteBtn).toBeVisible();
    await expect(writeBtn).toHaveCount(0);
  });

  test("rewriting an existing PRFAQ asks first", async ({ page }) => {
    await createAndSelectEvent(page, "PRFAQ Rewrite UI Test");
    await submitTeam(page, "NovaMind");
    await page.click('button:has-text("Next Team")');
    await page.click('button:has-text("Submissions")');
    await page.getByRole("button", { name: "Write PRFAQ", exact: true }).click();

    const panel = page.locator(".submission-item div[id^='prfaq-']");
    await expect(panel).toContainText("assumptions", { timeout: 60_000 });

    const rewriteBtn = page.getByRole("button", { name: "Rewrite PRFAQ", exact: true });

    // Dismissing the confirm leaves the stored document alone
    page.once("dialog", (d) => d.dismiss());
    await rewriteBtn.click();
    await expect(panel).toContainText("assumptions");
    await expect(rewriteBtn).toBeEnabled();

    // Accepting it regenerates in place
    page.once("dialog", (d) => d.accept());
    await rewriteBtn.click();
    await expect(panel).toContainText("assumptions", { timeout: 60_000 });
    await expect(rewriteBtn).toBeVisible();
  });

  test("generating PRFAQs for the whole event", async ({ page }) => {
    await createAndSelectEvent(page, "PRFAQ Batch UI Test");
    await submitTeam(page, "NovaMind");
    await page.click('button:has-text("Next Team")');
    await submitTeam(page, "ContextCraft");
    await page.click('button:has-text("Next Team")');
    await page.click('button:has-text("Submissions")');

    await page.click("#btn-prfaqs");
    await expect(page.locator("#export-status")).toContainText("2 written", {
      timeout: 120_000,
    });
    await expect(page.locator("#export-status")).toHaveClass(/success/);
  });
});

test.describe("Virtual Judge — API Integration", () => {
  test("full API round-trip without browser", async ({ request }) => {
    // Create event
    const eventRes = await request.post("/api/events", {
      data: { name: "API Test Event", description: "Testing via API" },
    });
    expect(eventRes.ok()).toBeTruthy();
    const event = await eventRes.json();

    // Create submission
    const subRes = await request.post("/api/submissions", {
      data: { team_name: "API Team", event_id: event.id },
    });
    expect(subRes.ok()).toBeTruthy();
    const sub = await subRes.json();

    // Upload audio (fake data)
    const audioRes = await request.post(
      `/api/submissions/${sub.id}/audio`,
      {
        multipart: {
          file: {
            name: "test.webm",
            mimeType: "audio/webm",
            buffer: Buffer.from("fake audio data for testing"),
          },
        },
      }
    );
    expect(audioRes.ok()).toBeTruthy();

    // Judge
    const judgeRes = await request.post(`/api/submissions/${sub.id}/judge`);
    expect(judgeRes.ok()).toBeTruthy();
    const result = await judgeRes.json();

    expect(result.status).toBe("complete");
    expect(result.scores).toHaveLength(4);
    expect(result.overall_score).toBeGreaterThan(0);
    expect(result.summary).toBeTruthy();
    expect(result.review_audio).toMatch(/\/audio\/.*_review\.mp3/);
    expect(result.transcript.length).toBeGreaterThan(500); // ~5 min pitch
  });

  test("export endpoints work after judging", async ({ request }) => {
    // Setup: create event + 1 judged submission
    const event = await (
      await request.post("/api/events", { data: { name: "Export Test" } })
    ).json();
    const sub = await (
      await request.post("/api/submissions", {
        data: { team_name: "ExportTeam", event_id: event.id },
      })
    ).json();
    await request.post(`/api/submissions/${sub.id}/audio`, {
      multipart: {
        file: {
          name: "t.webm",
          mimeType: "audio/webm",
          buffer: Buffer.from("audio"),
        },
      },
    });
    await request.post(`/api/submissions/${sub.id}/judge`);

    // CSV export
    const csvRes = await request.get(`/api/events/${event.id}/export/csv`);
    expect(csvRes.ok()).toBeTruthy();

    // JSON export
    const jsonRes = await request.get(`/api/events/${event.id}/export/json`);
    expect(jsonRes.ok()).toBeTruthy();
    const jsonData = await jsonRes.json();
    expect(jsonData.event).toBe("Export Test");
    expect(jsonData.submissions).toHaveLength(1);
  });

  test("PRFAQ generation, caching, and bundle export", async ({ request }) => {
    const event = await (
      await request.post("/api/events", { data: { name: "PRFAQ Test" } })
    ).json();
    const sub = await (
      await request.post("/api/submissions", {
        data: { team_name: "PrfaqTeam", event_id: event.id },
      })
    ).json();
    await request.post(`/api/submissions/${sub.id}/audio`, {
      multipart: {
        file: { name: "t.webm", mimeType: "audio/webm", buffer: Buffer.from("audio") },
      },
    });
    await request.post(`/api/submissions/${sub.id}/judge`);

    // Generate for the whole event
    const batchRes = await request.post(`/api/events/${event.id}/prfaqs`);
    expect(batchRes.ok()).toBeTruthy();
    const batch = await batchRes.json();
    expect(batch.generated).toContain("PrfaqTeam");
    expect(batch.failed).toHaveLength(0);

    // The document itself
    const prfaqRes = await request.get(`/api/submissions/${sub.id}/prfaq`);
    expect(prfaqRes.ok()).toBeTruthy();
    const prfaq = await prfaqRes.json();
    expect(prfaq.markdown).toContain("Nobody reviewed it");
    expect(prfaq.markdown).toContain("Assumptions Ledger");
    expect(prfaq.content.assumptions.length).toBeGreaterThan(0);

    // Re-running returns the stored one rather than rewriting it
    const cached = await (
      await request.post(`/api/submissions/${sub.id}/prfaq`)
    ).json();
    expect(cached.cached).toBe(true);

    // A second batch run skips it
    const rerun = await (await request.post(`/api/events/${event.id}/prfaqs`)).json();
    expect(rerun.generated).toHaveLength(0);
    expect(rerun.skipped[0].reason).toBe("already generated");

    // And it lands in the bundle
    const bundle = await (
      await request.get(`/api/events/${event.id}/export/bundle`)
    ).json();
    expect(bundle.prfaqs).toBe(1);
  });
});

test.describe("Virtual Judge — Switching Events", () => {
  test.beforeEach(async ({ page }) => {
    await injectFakeMediaStream(page);
    await page.goto("/");
  });

  /** Seed an event with one judged submission and a finalist round via the API. */
  async function seedEvent(page: Page, name: string, teams: string[]) {
    const event = await (
      await page.request.post("/api/events", { data: { name } })
    ).json();
    for (const team of teams) {
      const sub = await (
        await page.request.post("/api/submissions", {
          data: { team_name: team, event_id: event.id },
        })
      ).json();
      await page.request.post(`/api/submissions/${sub.id}/audio`, {
        multipart: {
          file: { name: "t.webm", mimeType: "audio/webm", buffer: Buffer.from("audio") },
        },
      });
      await page.request.post(`/api/submissions/${sub.id}/judge`);
    }
    return event;
  }

  test("switching events swaps the submissions list", async ({ page }) => {
    const alpha = await seedEvent(page, "Alpha Event", ["AlphaTeam"]);
    const beta = await seedEvent(page, "Beta Event", ["BetaTeam"]);
    await page.reload();

    await page.selectOption("#event-select", alpha.id);
    await page.click('button:has-text("Submissions")');
    await expect(page.locator("#submissions-list")).toContainText("AlphaTeam");
    await expect(page.locator("#submissions-list")).not.toContainText("BetaTeam");

    // Switching events must replace the list, not leave the previous one up.
    await page.selectOption("#event-select", beta.id);
    await expect(page.locator("#submissions-list")).toContainText("BetaTeam");
    await expect(page.locator("#submissions-list")).not.toContainText("AlphaTeam");
  });

  test("finalist results load for the selected event", async ({ page }) => {
    const alpha = await seedEvent(page, "Finalist Alpha", ["A1", "A2", "A3"]);
    await page.request.post(`/api/events/${alpha.id}/finalist`);
    const empty = await (
      await page.request.post("/api/events", { data: { name: "No Finalist Yet" } })
    ).json();
    await page.reload();

    // Stored results show up without re-running the round.
    await page.selectOption("#event-select", alpha.id);
    await page.click('button:has-text("Finalist")');
    await expect(page.locator("#finalist-results")).toBeVisible();
    await expect(page.locator("#finalist-results")).toContainText("A1");

    // An event with no finalist round shows an empty panel, not the last one's winners.
    await page.selectOption("#event-select", empty.id);
    await expect(page.locator("#finalist-results")).toBeHidden();
    await expect(page.locator("#finalist-results")).not.toContainText("A1");
  });

  test("switching events clears a judged result from the judge view", async ({ page }) => {
    const alpha = await seedEvent(page, "Judge View Alpha", ["JudgedTeam"]);
    const beta = await (
      await page.request.post("/api/events", { data: { name: "Judge View Beta" } })
    ).json();
    await page.reload();

    await page.selectOption("#event-select", alpha.id);
    await submitTeam(page, "LiveTeam");
    await expect(page.locator("#results-panel")).toBeVisible();

    await page.selectOption("#event-select", beta.id);
    await expect(page.locator("#results-panel")).toBeHidden();
    await expect(page.locator("#team-name")).toHaveValue("");
  });

  test("stored finalist results survive a page reload", async ({ page }) => {
    const event = await seedEvent(page, "Reload Finalist", ["R1", "R2", "R3"]);
    await page.request.post(`/api/events/${event.id}/finalist`);

    await page.reload();
    await page.selectOption("#event-select", event.id);
    await page.click('button:has-text("Finalist")');
    await expect(page.locator("#finalist-results")).toContainText("R1");
  });

  test("the finalist player is visible without scrolling", async ({ page }) => {
    const event = await seedEvent(page, "Player Placement", ["P1", "P2", "P3"]);
    await page.request.post(`/api/events/${event.id}/finalist`);
    await page.reload();

    await page.selectOption("#event-select", event.id);
    await page.click('button:has-text("Finalist")');

    const player = page.locator("#finalist-audio");
    await expect(player).toBeVisible();
    await expect(page.locator("#finalist-audio-wrap")).toBeVisible();

    // It used to render below the result cards and the cohort summary, ~1300px
    // down — present, playable, and never seen.
    const box = await player.boundingBox();
    const viewport = page.viewportSize();
    expect(box!.y).toBeLessThan(viewport!.height);
  });

  test("the finalist player is hidden for an event with no round", async ({ page }) => {
    const empty = await (
      await page.request.post("/api/events", { data: { name: "No Round Player" } })
    ).json();
    await page.reload();

    await page.selectOption("#event-select", empty.id);
    await page.click('button:has-text("Finalist")');
    await expect(page.locator("#finalist-audio-wrap")).toBeHidden();
  });
});
