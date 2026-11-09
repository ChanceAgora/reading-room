import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:18767', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: '../.venv/bin/python ../scripts/test_web_server.py',
    url: 'http://127.0.0.1:18767/api/ui/bootstrap',
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
