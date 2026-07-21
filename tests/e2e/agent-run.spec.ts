import { expect, test, type Page, type Route } from "@playwright/test";

const now = "2026-07-20T12:00:00Z";

function ok(data: unknown) {
  return { code: 0, message: "ok", data };
}

async function installMockApi(page: Page) {
  let repositories: Record<string, unknown>[] = [];
  let approvalStatus = "pending";

  const repository = {
    id: 7, space_id: 1, owner_id: 1, name: "demo-agent", clone_url: null,
    root_path: "C:/workspace/demo-agent", default_branch: "main", status: "ready",
    settings: null, created_at: now, updated_at: now,
  };
  const run = {
    id: 41, space_id: 1, user_id: 1, repository_id: 7, workflow_id: null,
    agent_id: null, title: "修复登录接口", prompt: "修复登录接口并补充完整的自动化测试。",
    permission_mode: "edit", status: "awaiting_approval", execution_id: "run-41",
    current_step: "plan", verification: null, error_message: null,
    started_at: now, finished_at: null, created_at: now, updated_at: now,
  };

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/v1/task-runs/41/events") {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          "id: 1-0", "event: output", "data: {\"subtask_id\":\"implementer\",\"content\":\"登录接口修复完成\"}", "",
          "id: 2-0", "event: terminal", "data: {\"line\":\"npm test -- --run\"}", "",
          "id: 3-0", "event: run", "data: {\"status\":\"succeeded\"}", "", "",
        ].join("\n"),
      });
      return;
    }
    if (path === "/api/v1/auth/login" && method === "POST") {
      await route.fulfill({ json: ok({
        access_token: "e2e-access", refresh_token: "e2e-refresh", expires_in: 3600,
        user: { id: 1, username: "engineer", email: "engineer@example.com", nickname: "工程师" },
      }) }); return;
    }
    if (path === "/api/v1/spaces/mine") {
      await route.fulfill({ json: ok([{ id: 1, name: "E2E 空间", description: "mock", owner_id: 1 }]) }); return;
    }
    if (path === "/api/v1/stats/overview") {
      await route.fulfill({ json: ok({ total_tasks: 0, succeeded: 0, tasks_last_30d: 0, knowledge_total: 0, reuse_rate: 0 }) }); return;
    }
    if (path === "/api/v1/stats/recent-tasks") {
      await route.fulfill({ json: ok([]) }); return;
    }
    if (path === "/api/v1/repositories" && method === "GET") {
      await route.fulfill({ json: ok(repositories) }); return;
    }
    if (path === "/api/v1/repositories" && method === "POST") {
      repositories = [repository];
      await route.fulfill({ json: ok(repository) }); return;
    }
    if (path === "/api/v1/task-runs" && method === "GET") {
      await route.fulfill({ json: ok([]) }); return;
    }
    if (path === "/api/v1/task-runs" && method === "POST") {
      const payload = request.postDataJSON();
      expect(payload).toMatchObject({
        repository_id: 7, title: "修复登录接口",
        prompt: "修复登录接口并补充完整的自动化测试。", permission_mode: "edit",
      });
      await route.fulfill({ json: ok(run) }); return;
    }
    if (path === "/api/v1/task-runs/41") {
      await route.fulfill({ json: ok(run) }); return;
    }
    if (path === "/api/v1/task-runs/41/steps") {
      await route.fulfill({ json: ok([{
        id: 101, task_run_id: 41, sequence: 0, role: "planner", name: "生成执行计划",
        status: "succeeded", input: { prompt: run.prompt }, output: { steps: 3 },
        error_message: null, started_at: now, finished_at: now, created_at: now, updated_at: now,
      }]) }); return;
    }
    if (path === "/api/v1/task-runs/41/approvals") {
      await route.fulfill({ json: ok([{
        id: 501, task_run_id: 41, operation: "plan", reason: "执行前确认计划",
        requested_by: 1, decided_by: approvalStatus === "pending" ? null : 1,
        status: approvalStatus, comment: null, decided_at: approvalStatus === "pending" ? null : now,
        created_at: now, updated_at: now,
      }]) }); return;
    }
    if (path === "/api/v1/approvals/501/decision" && method === "POST") {
      expect(request.postDataJSON()).toEqual({ decision: "approved" });
      approvalStatus = "approved";
      await route.fulfill({ json: ok({
        id: 501, task_run_id: 41, operation: "plan", reason: "执行前确认计划",
        requested_by: 1, decided_by: 1, status: "approved", comment: null,
        decided_at: now, created_at: now, updated_at: now,
      }) }); return;
    }
    if (path === "/api/v1/task-runs/41/artifacts") {
      await route.fulfill({ json: ok([{
        id: 701, task_run_id: 41, kind: "diff", name: "changes.patch", path: "artifacts/changes.patch",
        mime_type: "text/x-diff", size: 96, checksum: "e2e", metadata: null,
        created_at: now, updated_at: now,
      }]) }); return;
    }
    if (path === "/api/v1/task-runs/41/tool-invocations") {
      await route.fulfill({ json: ok([{
        id: 601, task_run_id: 41, run_step_id: 101, agent_name: "tester", tool_name: "test",
        input: { command: "npm test -- --run" },
        result: { status: "succeeded", summary: "9 tests passed", next_actions: [], artifacts: [] },
        status: "succeeded", duration_ms: 812, created_at: now, updated_at: now,
      }]) }); return;
    }
    if (path === "/api/v1/task-runs/41/diff") {
      await route.fulfill({ json: ok({
        task_run_id: 41,
        unified_diff: "diff --git a/src/login.ts b/src/login.ts\n+export const login = () => true;",
        verified: true,
      }) }); return;
    }
    await route.fulfill({ status: 404, json: { code: 404, message: `No mock for ${method} ${path}`, data: null } });
  });
}

test("login, repository registration, TaskRun approval and delivery evidence", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/login");

  await page.getByPlaceholder("用户名或邮箱").fill("engineer");
  await page.getByPlaceholder("密码").first().fill("Passw0rd!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByText("E2E 空间")).toBeVisible();

  await page.getByRole("menuitem", { name: "代码仓库" }).click();
  await page.getByRole("button", { name: "接入仓库" }).click();
  await page.getByPlaceholder("zhixiao-agent", { exact: true }).fill("demo-agent");
  await page.getByPlaceholder("/workspace/zhixiao-agent").fill("C:/workspace/demo-agent");
  await page.getByRole("button", { name: "校验并接入" }).click();
  await expect(page.getByText("C:/workspace/demo-agent")).toBeVisible();

  await page.getByRole("button", { name: "创建任务" }).click();
  await page.getByPlaceholder("例如：为用户资料页增加头像上传").fill("修复登录接口");
  await page.getByPlaceholder(/描述期望行为/).fill("修复登录接口并补充完整的自动化测试。");
  await page.getByRole("button", { name: "提交并跳转" }).click();

  await expect(page).toHaveURL(/\/task\/41$/);
  await expect(page.getByText("执行前确认计划")).toBeVisible();
  await page.getByRole("button", { name: "批准并继续" }).click();
  await expect(page.getByText("执行前确认计划")).toBeHidden();

  await expect(page.getByText("登录接口修复完成")).toBeVisible();
  await page.getByRole("tab", { name: "终端" }).click();
  await expect(page.locator("pre.terminal")).toContainText("npm test -- --run");
  await page.getByRole("tab", { name: "Diff" }).click();
  await expect(page.locator("pre.diff-view")).toContainText("export const login");
  await page.getByRole("tab", { name: "测试结果" }).click();
  await expect(page.getByText("9 tests passed", { exact: true })).toBeVisible();
});
