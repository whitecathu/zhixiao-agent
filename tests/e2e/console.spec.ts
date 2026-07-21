import { expect, test } from "@playwright/test";

test("unauthenticated user reaches the engineering-agent login console", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page).toHaveTitle("登录");
  await expect(page.getByRole("heading", { name: /从工程目标/ })).toBeVisible();
  await expect(page.getByText("登录工程 Agent 控制台")).toBeVisible();
});

test("web health endpoint is reachable", async ({ request }) => {
  const webHealth = await request.get("/health");
  expect(webHealth.ok()).toBeTruthy();
});
