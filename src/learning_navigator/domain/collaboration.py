"""Stable collaboration semantics shared across API, persistence, and UI layers."""

from __future__ import annotations

from enum import StrEnum


class ConversationMessageOrigin(StrEnum):
    """Who initiated a user-role collaboration message."""

    USER_INPUT = "USER_INPUT"
    PROJECT_CREATION_SHORTCUT = "PROJECT_CREATION_SHORTCUT"


NEW_PROJECT_DISCOVERY_PROMPT = (
    "我想新建一个项目。请先通过对话帮我澄清目标、现状、限制与成功标准，"
    "再逐步形成一份可编辑的框架和路径草稿；在我明确确认前不要建立正式项目。"
)
