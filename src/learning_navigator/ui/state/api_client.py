"""HTTP-only UI gateway. NiceGUI pages never import repositories or database models."""

from typing import Any

import httpx

AI_ERROR_MESSAGES = {
    "timeout_error": "AI 服务响应超时，请稍后重试。",
    "invalid_response": "AI 服务返回了无法识别的内容，请重试或更换模型。",
    "upstream_error": "AI 服务暂时不可用，请稍后重试。",
    "connection_error": "无法连接到 AI 服务，请检查 AI 设置。",
    "authentication_error": "AI 服务认证失败，请检查 API Key。",
    "rate_limit_error": "AI 服务请求过于频繁，请稍后重试。",
    "configuration_error": "AI 配置不完整，请检查 AI 设置。",
    "request_error": "AI 服务拒绝了当前请求，请调整输入后重试。",
    "revision_conflict": "路径已在其他位置更新，请刷新后继续编辑。",
    "invalid_path_revision": "路径存在结构错误，请校验节点与关系后重试。",
    "invalid_state_transition": "当前版本不能执行这个操作，请先创建可编辑草稿。",
    "circular_prerequisite": "这个前置关系会形成循环，框架未被修改。",
    "duplicate_edge": "这条关系已经存在。",
    "entity_not_found": "目标内容不存在，或已被归档。",
    "duplicate_progress_check_in": "今天已经打卡，可使用修改功能调整评分或备注。",
    "progress_score_regression": "新打卡的进度不能低于当前评分；如需纠正，请修改已有记录。",
    "progress_check_in_revision_conflict": "打卡记录已被更新，请刷新后再修改。",
}


class UIAPIError(RuntimeError):
    pass


class UIAPIClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 20.0,
        ai_timeout: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.ai_timeout = ai_timeout
        self.transport = transport

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, *, json: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json=json)

    async def patch(self, path: str, *, json: dict[str, Any]) -> Any:
        return await self._request("PATCH", path, json=json)

    async def delete(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._request("DELETE", path, params=params)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        timeout = self.ai_timeout if path.startswith("/ai/") else self.timeout
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
                response = await client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.TimeoutException:
            raise UIAPIError("请求超时，请稍后重试。") from None
        except httpx.RequestError:
            raise UIAPIError("无法连接到服务，请确认服务已启动。") from None
        if response.is_error:
            raise UIAPIError(_safe_http_error_message(response))
        if response.status_code == 204:
            return None
        return response.json()


def _safe_http_error_message(response: httpx.Response) -> str:
    """Return a user-facing error without reflecting upstream bodies or request URLs."""

    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            code = detail.get("code")
            if isinstance(code, str) and code in AI_ERROR_MESSAGES:
                return AI_ERROR_MESSAGES[code]
    return f"请求失败（HTTP {response.status_code}），请稍后重试。"
