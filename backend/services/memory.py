from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.domain import UserContext
from backend.services.access_control import normalize_user_context


PRODUCT_ALIASES = {
    "orion": "Orion 协作平台",
    "协作平台": "Orion 协作平台",
}

TOPIC_KEYWORDS = {
    "账号权限": ("权限", "角色", "SSO", "登录", "账号", "访问"),
    "安全合规": ("安全", "合规", "审计", "泄露", "白名单", "外部分享"),
    "IT 支持": ("电脑", "VPN", "密码", "设备", "客户端"),
    "费用审批": ("费用", "采购", "审批", "预算", "报销"),
    "事故响应": ("事故", "P1", "故障", "响应", "升级"),
    "知识治理": ("知识库", "文档", "过期", "治理", "引用"),
}


class UserMemoryStore:
    def __init__(self, path: Path, max_recent_questions: int = 5):
        self.path = path
        self.max_recent_questions = max(1, max_recent_questions)

    def recall(self, user_context: UserContext | dict[str, Any] | None) -> dict[str, Any]:
        user = normalize_user_context(user_context)
        payload = self._load()
        memory = payload.get("users", {}).get(user.user_id, {})
        return {
            "user_id": user.user_id,
            "profile": dict(memory.get("profile", {})),
            "topic_counts": dict(memory.get("topic_counts", {})),
            "recent_questions": list(memory.get("recent_questions", [])),
        }

    def enrich_question(self, question: str, memory: dict[str, Any]) -> str:
        preferred_product = memory.get("profile", {}).get("preferred_product")
        if not preferred_product:
            return question
        vague_refs = ("这个平台", "该平台", "上次那个平台", "上次那个产品", "它")
        if any(ref in question for ref in vague_refs) and preferred_product not in question:
            return f"{question}（用户长期记忆：这里的产品通常指 {preferred_product}）"
        return question

    def memory_context(self, memory: dict[str, Any]) -> str:
        lines = []
        profile = memory.get("profile", {})
        if profile.get("preferred_product"):
            lines.append(f"- 常关注产品：{profile['preferred_product']}")
        topic_counts = memory.get("topic_counts", {})
        if topic_counts:
            ranked = sorted(topic_counts.items(), key=lambda item: item[1], reverse=True)[:3]
            lines.append("- 历史关注主题：" + "、".join(f"{topic}({count})" for topic, count in ranked))
        return "\n".join(lines)

    def update(
        self,
        user_context: UserContext | dict[str, Any] | None,
        question: str,
        answer: str,
    ) -> dict[str, Any]:
        user = normalize_user_context(user_context)
        payload = self._load()
        users = payload.setdefault("users", {})
        memory = users.setdefault(
            user.user_id,
            {
                "profile": {},
                "topic_counts": {},
                "recent_questions": [],
                "updated_at": None,
            },
        )
        learned = []
        preferred_product = self._extract_preferred_product(question)
        if preferred_product and memory.setdefault("profile", {}).get("preferred_product") != preferred_product:
            memory["profile"]["preferred_product"] = preferred_product
            learned.append(f"preferred_product={preferred_product}")

        for topic in self._extract_topics(question):
            topic_counts = memory.setdefault("topic_counts", {})
            topic_counts[topic] = int(topic_counts.get(topic, 0)) + 1
            learned.append(f"topic={topic}")

        recent_questions = memory.setdefault("recent_questions", [])
        recent_questions.append(question)
        memory["recent_questions"] = recent_questions[-self.max_recent_questions :]
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save(payload)
        return {
            "user_id": user.user_id,
            "learned": sorted(set(learned)),
            "profile": dict(memory.get("profile", {})),
            "topic_counts": dict(memory.get("topic_counts", {})),
            "answer_chars_observed": len(answer),
        }

    def _extract_preferred_product(self, question: str) -> str | None:
        normalized = question.lower()
        for keyword, product in PRODUCT_ALIASES.items():
            if keyword.lower() in normalized:
                return product
        return None

    def _extract_topics(self, question: str) -> list[str]:
        topics = []
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword.lower() in question.lower() for keyword in keywords):
                topics.append(topic)
        return topics

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"users": {}}

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
