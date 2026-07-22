"""app/main.py
FastAPI 应用入口 - 中间件、路由、生命周期、OpenAPI 分组
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.metrics import PrometheusMiddleware
from app.core.middleware import RateLimitMiddleware, TraceIdMiddleware
from app.core.redis_client import RedisClient
from app.db.session import dispose_engine
from app.router import (
    auth,
    knowledge,
    observability,
    onboarding,
    platform,
    space,
    sse,
    stats,
    task,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # The registry provides an in-process adapter and accepts a worker adapter at deployment time.
    yield
    await RedisClient.close()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="智效工坊后端服务",
        description="多 Agent 协同任务执行与知识沉淀平台 - FastAPI 后端",
        version="1.0.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "认证", "description": "用户注册 / 登录 / 令牌管理"},
            {"name": "团队空间", "description": "空间与成员管理"},
            {"name": "任务", "description": "任务创建 / 状态 / 控制"},
            {"name": "SSE 执行流", "description": "实时流式输出"},
            {"name": "知识", "description": "知识条目与混合检索"},
            {"name": "统计与回溯", "description": "工作台首页 / 链路回溯"},
        ],
    )

    # 中间件 - 顺序：外 -> 内  => 后加的最先执行
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS
        if isinstance(settings.CORS_ORIGINS, list)
        else [settings.CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id", "X-Duration-Ms"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(PrometheusMiddleware)

    # 路由
    app.include_router(auth.router)
    app.include_router(space.router)
    app.include_router(task.router)
    app.include_router(sse.router)
    # Register static platform subpaths (for example /knowledge/graph) before
    # the legacy /knowledge/{knowledge_id} route.
    app.include_router(platform.router)
    app.include_router(observability.router)
    app.include_router(onboarding.router)
    app.include_router(knowledge.router)
    app.include_router(stats.router)

    register_exception_handlers(app)

    @app.get("/health", tags=["系统"], summary="健康检查")
    async def health():
        return {"status": "ok", "env": settings.APP_ENV}

    return app


app = create_app()


def run() -> None:
    """Installed console entry point."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    run()
