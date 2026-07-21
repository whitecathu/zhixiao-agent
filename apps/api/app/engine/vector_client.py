"""app/engine/vector_client.py
Chroma 向量库客户端 - 单例 + 健康降级
GOAL-06 抽象 VectorStore 时不影响此文件签名
"""

from typing import Optional

from app.core.config import settings

_collection: Optional[object] = None


def chroma_collection():
    """返回 Chroma Collection（或 None 表示降级）"""
    global _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb

        client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
        _collection = client.get_or_create_collection(name=settings.CHROMA_COLLECTION)
        return _collection
    except Exception:
        # 健康降级：返回 None，上层走关键词检索
        return None


def reset() -> None:
    """测试用：重置客户端"""
    global _collection
    _collection = None
