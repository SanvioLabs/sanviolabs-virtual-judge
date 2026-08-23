import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Deliberately NOT 8000 — that's the dev server's port. The suite used to share
// it and reuse whatever was already listening, so running tests while
// `npm run dev` was up silently pointed them at a real-mode server: the mocks
// were bypassed, every "recording" hit the live transcription and TTS APIs, and
// the failures looked like application bugs.
const PORT = Number(process.env.VJ_TEST_PORT) || 8100;

// A throwaway database. The suite starts a real server, and the default path is
// judge.db in the project root — the file holding actual event results. Every
// run used to file its fixtures in there, which is where a drift of "API Test
// Event" and "Export Test" rows came from.
//
// The wipe is guarded because this config is re-evaluated in every worker
// process, not just once. Unguarded, a worker starting up deletes the database
// the server is already serving from, and every request after that 500s on a
// table that no longer exists.
const DB_PATH = path.join(os.tmpdir(), `virtual-judge-e2e-${PORT}.db`);
if (!process.env.VJ_E2E_DB_PREPARED) {
  for (const suffix of ["", "-wal", "-shm"]) {
    fs.rmSync(DB_PATH + suffix, { force: true });
  }
  process.env.VJ_E2E_DB_PREPARED = "1";
}

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
    command: `MOCK_EXTERNALS=true VJ_DB_PATH=${DB_PATH} uv run uvicorn server:app --port ${PORT}`,
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
