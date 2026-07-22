import { expect, test, type Page, type Route } from "@playwright/test";

const now = "2026-07-22T09:00:00Z";

function ok(data: unknown) {
  return { code: 0, message: "ok", data };
}

async function installProductApi(page: Page) {
  let onboardingSkipped = false;
  const workflow = {
    id: 9,
    space_id: 1,
    name: "跨栈交付流",
    version: 2,
    enabled: true,
    status: "published",
    published_at: now,
    definition: {
      schema_version: 1,
      entrypoint: "plan",
      nodes: [
        {
          id: "plan",
          role: "planner",
          label: "制定计划",
          position: { x: 80, y: 120 },
          tool_allowlist: [],
          retry_limit: 0,
          approval_required: true,
        },
        {
          id: "implement",
          role: "implementer",
          label: "实现变更",
          position: { x: 320, y: 120 },
          tool_allowlist: ["read_file", "exact_edit"],
          retry_limit: 1,
          approval_required: false,
        },
      ],
      edges: [{ source: "plan", target: "implement", condition: "success" }],
    },
    created_at: now,
    updated_at: now,
  };
  const onboardingState = () => ({
    steps: [
      { id: "select_space", label: "选择工作空间", completed: false },
      { id: "connect_repository", label: "接入代码仓库", completed: false },
      { id: "create_task", label: "创建首个 Agent 任务", completed: false },
      { id: "approve_plan", label: "审批执行计划", completed: false },
      { id: "inspect_delivery", label: "查看 Diff 与验证证据", completed: false },
    ],
    completed_steps: [],
    skipped: onboardingSkipped,
    finished: onboardingSkipped,
    current_step: onboardingSkipped ? null : "select_space",
    replay_count: 0,
  });

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/v1/auth/login" && method === "POST") {
      await route.fulfill({
        json: ok({
          access_token: "product-access",
          refresh_token: "product-refresh",
          expires_in: 3600,
          user: {
            id: 1,
            username: "admin",
            email: "admin@example.com",
            nickname: "空间管理员",
          },
        }),
      });
      return;
    }
    if (path === "/api/v1/spaces/mine") {
      await route.fulfill({
        json: ok([{ id: 1, name: "产品空间", description: "E2E", owner_id: 1 }]),
      });
      return;
    }
    if (path === "/api/v1/spaces/1/members") {
      await route.fulfill({
        json: ok([{ id: 1, user_id: 1, role: "space_admin" }]),
      });
      return;
    }
    if (path === "/api/v1/stats/overview") {
      await route.fulfill({
        json: ok({
          total_tasks: 2,
          succeeded: 1,
          tasks_last_30d: 2,
          knowledge_total: 3,
          reuse_rate: 0.5,
        }),
      });
      return;
    }
    if (path === "/api/v1/stats/recent-tasks") {
      await route.fulfill({ json: ok([]) });
      return;
    }
    if (path === "/api/v1/onboarding/me" && method === "GET") {
      await route.fulfill({ json: ok(onboardingState()) });
      return;
    }
    if (path === "/api/v1/onboarding/me/skip" && method === "POST") {
      onboardingSkipped = true;
      await route.fulfill({ json: ok(onboardingState()) });
      return;
    }
    if (path === "/api/v1/onboarding/config" && method === "GET") {
      await route.fulfill({
        json: ok({ space_id: 1, recommended_template: null, default_workflow_id: 9 }),
      });
      return;
    }
    if (path === "/api/v1/workflows" && method === "GET") {
      await route.fulfill({ json: ok([workflow]) });
      return;
    }
    if (path === "/api/v1/observability/summary") {
      await route.fulfill({
        json: ok({
          generated_at: now,
          window: "24h",
          window_days: 1,
          tasks: {
            total: 2,
            active: 1,
            queued: 1,
            running: 0,
            awaiting_approval: 0,
            succeeded: 1,
            failed: 0,
            success_rate: 1,
            first_pass_rate: 1,
            p95_duration_seconds: 42,
          },
          tools: {
            total: 4,
            succeeded: 4,
            failed: 0,
            blocked: 0,
            success_rate: 1,
            average_duration_seconds: 0.3,
            invocations: 4,
            failure_rate: 0,
            p95_duration_ms: 500,
          },
          approvals: {
            pending: 0,
            decided: 1,
            average_wait_seconds: 8,
            p95_wait_seconds: 8,
          },
          queue_backlog: 1,
          queue: { depth: 1, oldest_age_seconds: 12 },
          model_usage: { prompt_tokens: 100, completion_tokens: 30, cost_usd: 0.01 },
          models: [
            { provider: "deepseek", model: "deepseek-chat", tokens: 130, cost_usd: 0.01, calls: 1 },
          ],
          recent_failures: [],
          slo: {
            task_success_rate: 1,
            first_pass_rate: 1,
            p95_run_duration_ms: 42000,
            error_rate: 0,
            cost_usd: 0.01,
            budget_usd: 10,
          },
        }),
      });
      return;
    }
    if (path === "/api/v1/knowledge/graph/explore" && method === "POST") {
      await route.fulfill({
        json: ok({
          entities: [
            {
              id: 11,
              space_id: 1,
              name: "TaskRun",
              entity_type: "class",
              properties: { module: "app.model.platform" },
              source_refs: [{ source: "app/model/platform.py" }],
              created_at: now,
              updated_at: now,
            },
          ],
          relations: [],
          truncated: false,
          retrieval_mode: "relational_graph",
          evidence_sufficient: true,
          evidence_status: "supported",
        }),
      });
      return;
    }
    if (path === "/api/v1/evaluations" && method === "GET") {
      await route.fulfill({ json: ok([]) });
      return;
    }
    await route.fulfill({
      status: 404,
      json: { code: 404, message: `No mock for ${method} ${path}`, data: null },
    });
  });
}

test("admin completes onboarding and uses observability, workflow, and graph surfaces", async ({
  page,
}) => {
  await installProductApi(page);
  await page.goto("/login");
  await page.getByPlaceholder("用户名或邮箱").fill("admin");
  await page.getByPlaceholder("密码").first().fill("Passw0rd!");
  await page.getByRole("button", { name: "登录", exact: true }).click();

  await expect(page.getByRole("heading", { name: "完成第一次 Agent 交付" })).toBeVisible();
  await page.getByRole("button", { name: "稍后再说" }).click();
  await expect(page.getByRole("heading", { name: "完成第一次 Agent 交付" })).toBeHidden();

  await page.getByRole("menuitem", { name: "运行观测" }).click();
  await expect(page.getByRole("heading", { name: "运行观测" })).toBeVisible();
  await expect(page.getByText("100.0%", { exact: true }).first()).toBeVisible();

  await page.getByRole("menuitem", { name: "工作流" }).click();
  await expect(page.getByRole("heading", { name: "工作流画布" })).toBeVisible();
  await expect(page.getByText("跨栈交付流", { exact: true })).toBeVisible();
  await expect(page.getByLabel("可拖拽角色节点")).toBeVisible();

  await page.getByRole("menuitem", { name: "图谱与评测" }).click();
  await expect(page.getByRole("heading", { name: "图谱与评测" })).toBeVisible();
  await expect(page.getByText("TaskRun", { exact: true })).toBeVisible();
  await expect(page.getByText("1 实体 · 0 关系", { exact: true })).toBeVisible();
});
