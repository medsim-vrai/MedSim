import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './test/e2e',
  fullyParallel: false,           // perf tests need a quiet machine
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'desktop-webkit',   use: { ...devices['Desktop Safari'] } },
    { name: 'ios-sim',          use: { ...devices['iPad (gen 7) landscape'] } },
    { name: 'android-emu',      use: { ...devices['Galaxy Tab S4 landscape'] } },
  ],
  webServer: {
    command: 'pnpm preview',
    port: 4173,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
