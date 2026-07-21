"""app/engine/registry.py
执行引擎注册中心 - 默认本地生命周期适配器，部署时可绑定 Worker 引擎。
"""

from typing import Optional

from app.engine.abstract_engine import AbstractExecutionEngine


_engine: Optional[AbstractExecutionEngine] = None


def register_engine(engine: AbstractExecutionEngine) -> None:
    global _engine
    _engine = engine


def get_engine() -> AbstractExecutionEngine:
    global _engine
    if _engine is None:
        from app.engine.local_engine import InProcessExecutionEngine

        _engine = InProcessExecutionEngine()
    return _engine


def get_execution_engine() -> AbstractExecutionEngine:
    """FastAPI dependency boundary; tests and deployments can override it."""
    return get_engine()
