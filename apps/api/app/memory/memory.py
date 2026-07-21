"""app/memory/memory.py
MetaGPT Memory 模式 - 长期记忆 + 工作记忆 + 向量检索
"""

from typing import Any, List, Optional

from app.schemas.message import Message


class Memory:
    """记忆系统 - 参考脚本内的 MetaGPT Memory 设计（轻量自实现版本）"""

    def __init__(self, chroma_collection: Optional[Any] = None):
        self.messages: List[Message] = []
        self.working: List[Message] = []  # 当前任务工作记忆
        self.chroma_collection = chroma_collection

    def add(self, message: Message, working: bool = True) -> None:
        self.messages.append(message)
        if working:
            self.working.append(message)
        if self.chroma_collection is not None and isinstance(message.content, str):
            try:
                self.chroma_collection.add(
                    documents=[message.content],
                    metadatas=[
                        {
                            "role": message.role,
                            "cause_by": message.cause_by,
                            "sent_from": message.sent_from,
                        }
                    ],
                    ids=[message.id],
                )
            except Exception:
                pass  # 向量写入失败仅降级，不影响主流程

    def get_by_actions(self, action_types: List[str]) -> List[Message]:
        return [m for m in self.messages if m.cause_by in action_types]

    def search(self, query: str, top_k: int = 5) -> List[Message]:
        if self.chroma_collection is None:
            q = query.lower()
            return [m for m in self.messages if q in str(m.content).lower()][:top_k]
        try:
            results = self.chroma_collection.query(query_texts=[query], n_results=top_k)
            ids = results["ids"][0] if results.get("ids") else []
            return [m for m in self.messages if m.id in ids]
        except Exception:
            return []

    def clear_working(self) -> None:
        self.working.clear()
