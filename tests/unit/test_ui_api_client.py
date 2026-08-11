"""HTTP gateway behavior for NiceGUI pages."""

import httpx
import pytest

from learning_navigator.ui.state.api_client import UIAPIClient, UIAPIError


@pytest.mark.anyio
async def test_success_returns_json_and_uses_short_timeout_for_non_ai() -> None:
    seen_timeout: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeout.append(request.extensions.get("timeout", {}).get("read"))
        return httpx.Response(200, json={"ok": True})

    client = UIAPIClient(
        "https://internal.test/api",
        timeout=7.0,
        ai_timeout=301.0,
        transport=httpx.MockTransport(handler),
    )

    assert await client.get("/health") == {"ok": True}
    assert seen_timeout == [7.0]


@pytest.mark.anyio
async def test_ai_request_uses_long_timeout() -> None:
    seen_timeout: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeout.append(request.extensions.get("timeout", {}).get("read"))
        return httpx.Response(201, json={"id": "suggestion"})

    client = UIAPIClient(
        "https://internal.test/api",
        timeout=7.0,
        ai_timeout=301.0,
        transport=httpx.MockTransport(handler),
    )

    assert await client.post("/ai/learning-plans/generate", json={}) == {"id": "suggestion"}
    assert seen_timeout == [301.0]


@pytest.mark.anyio
async def test_delete_can_send_server_side_confirmation_body() -> None:
    captured: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((request.method, request.content))
        return httpx.Response(204)

    client = UIAPIClient(
        "https://internal.test/api",
        transport=httpx.MockTransport(handler),
    )

    assert await client.delete("/goals/goal-1", json={"confirm_title": "目标 A"}) is None
    assert captured == [("DELETE", b'{"confirm_title":"\xe7\x9b\xae\xe6\xa0\x87 A"}')]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("timeout_error", "AI 服务响应超时，请稍后重试。"),
        ("invalid_response", "AI 服务返回了无法识别的内容，请重试或更换模型。"),
        ("upstream_error", "AI 服务暂时不可用，请稍后重试。"),
        ("connection_error", "无法连接到 AI 服务，请检查 AI 设置。"),
        ("authentication_error", "AI 服务认证失败，请检查 API Key。"),
        ("rate_limit_error", "AI 服务请求过于频繁，请稍后重试。"),
        ("duplicate_progress_check_in", "今天已经打卡，可使用修改功能调整评分或备注。"),
        (
            "progress_score_regression",
            "新打卡的进度不能低于当前评分；如需纠正，请修改已有记录。",
        ),
        ("progress_check_in_revision_conflict", "打卡记录已被更新，请刷新后再修改。"),
        (
            "node_in_active_path",
            "该节点仍被当前项目路径引用；请先在路径编辑中移除或替换它。",
        ),
        (
            "ai_provider_profile_in_use",
            "该 AI 连接仍被活动对话使用；请先切换连接或归档相关对话。",
        ),
    ],
)
async def test_nested_ai_error_uses_safe_chinese_message(code: str, message: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={
                "detail": {
                    "code": code,
                    "message": "secret upstream body at https://private.example",
                    "retryable": True,
                }
            },
        )

    client = UIAPIClient(
        "https://internal.test/api",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UIAPIError) as caught:
        await client.post("/ai/learning-plans/generate", json={})
    assert str(caught.value) == message
    assert "private.example" not in str(caught.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            502,
            json={"detail": {"code": "unknown", "message": "secret upstream body"}},
        ),
        httpx.Response(502, text="secret raw upstream body"),
        httpx.Response(422, json={"detail": "secret validation body"}),
    ],
)
async def test_unknown_http_error_safely_degrades(response: httpx.Response) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    client = UIAPIClient(
        "https://internal.test/api",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UIAPIError) as caught:
        await client.get("/health")
    expected = f"请求失败（HTTP {response.status_code}），请稍后重试。"
    assert str(caught.value) == expected
    assert "secret" not in str(caught.value)


@pytest.mark.anyio
async def test_timeout_is_sanitized() -> None:
    secret_url = "https://secret.internal/api/ai/learning-plans/generate"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out calling {secret_url}", request=request)

    client = UIAPIClient(
        "https://secret.internal/api",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UIAPIError) as caught:
        await client.post("/ai/learning-plans/generate", json={})
    assert str(caught.value) == "请求超时，请稍后重试。"
    assert "secret.internal" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.anyio
async def test_connection_failure_is_sanitized() -> None:
    secret_url = "https://secret.internal/api/health"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed to connect to {secret_url}", request=request)

    client = UIAPIClient(
        "https://secret.internal/api",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UIAPIError) as caught:
        await client.get("/health")
    assert str(caught.value) == "无法连接到服务，请确认服务已启动。"
    assert "secret.internal" not in str(caught.value)
    assert caught.value.__cause__ is None
