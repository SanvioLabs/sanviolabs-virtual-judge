import { defineConfig } from "@playwright/test";

// Deliberately NOT 8000 — that's the dev server's port. The suite used to share
// it and reuse whatever was already listening, so running tests while
// `npm run dev` was up silently pointed them at a real-mode server: the mocks
// were bypassed, every "recording" hit the live transcription and TTS APIs, and
// the failures looked like application bugs.
const PORT = Number(process.env.VJ_TEST_PORT) || 8100;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
    permissions: ["microphone"],
  },
  webServer: {
    command: `MOCK_EXTERNALS=true uv run uvicorn server:app --port ${PORT}`,
    port: PORT,
    // Never reuse: the suite must own a server it knows is in mock mode.
    reuseExistingServer: false,
    timeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        browserName: "chromium",
        launchOptions: {
          args: [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
          ],
        },
      },
    },
  ],
});
