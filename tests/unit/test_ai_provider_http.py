"""Provider transport contracts, safe failures and editable preset defaults."""

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from learning_navigator.application.dto.ai import LearningPlanDraft
from learning_navigator.application.dto.collaboration import CollaborationAIResponse
from learning_navigator.infrastructure.ai.providers import (
    PROVIDER_PRESETS,
    AIProviderError,
    AnthropicProvider,
    GeminiProvider,
    MockProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    _collaboration_prompt,
    _learning_plan_prompt,
    _normalize_collaboration_payload,
    _normalize_learning_plan_payload,
    build_provider,
)


def test_plan_prompts_prefer_compact_complete_module_children() -> None:
    plan_prompt = _learning_plan_prompt("Broad field", "Use 6 to 8 modules")
    collaboration_prompt = _collaboration_prompt(
        {
            "conversation": {"purpose": "PLANNING"},
            "messages": [],
            "project": {"exists": False, "goal_id": None},
        }
    )

    assert "prefer exactly 2 concrete children per module" in plan_prompt
    assert "full JSON fits without truncation" in plan_prompt
    assert "never create a standalone ungrouped target" in plan_prompt
    assert "detailed_description is a practical explanation" in plan_prompt
    assert "should be able to do after understanding it" in plan_prompt
    assert "normally contain only 2 concrete children" in collaboration_prompt
    assert "complete JSON is never truncated" in collaboration_prompt
    assert "never create a standalone ungrouped target" in collaboration_prompt
    assert "latest user message is the task to complete now" in collaboration_prompt
    assert "Never substitute a report about an earlier tool change" in collaboration_prompt


def test_plan_prompt_preserves_an_explicit_user_outline_instead_of_recounting_it() -> None:
    prompt = _learning_plan_prompt(
        "系统性补数学基础",
        """第一阶段：初中数学基础重建
第二阶段：高中数学核心
第三阶段：高等数学基础
第四阶段：线性代数
第五阶段：概率统计
第六阶段：AI/量化数学应用""",
    )

    assert "exactly 6 MODULE nodes" in prompt
    assert "Do not apply the generic module or child-count heuristics" in prompt
    assert "Preserve every distinct bullet item" in prompt
    assert "every child must appear exactly once" in prompt
    assert "compact skeleton" in prompt
    assert "Never avoid truncation by dropping or merging" in prompt
    assert "初中数学基础重建" in prompt
    assert "AI/量化数学应用" in prompt


def test_plan_normalization_moves_the_declared_target_stage_to_the_end() -> None:
    payload = _learning_plan_payload()
    stages = payload["navigation"]["stages"]
    target_id = payload["navigation"]["target_temp_id"]
    target_index = next(
        index for index, stage in enumerate(stages) if target_id in stage["node_temp_ids"]
    )
    target_stage = stages.pop(target_index)
    stages.insert(0, target_stage)
    for sequence, stage in enumerate(stages, start=1):
        stage["sequence"] = sequence

    normalized = _normalize_learning_plan_payload(payload)
    validated = LearningPlanDraft.model_validate(normalized)

    assert target_id in validated.navigation.stages[-1].node_temp_ids
    assert [stage.sequence for stage in validated.navigation.stages] == list(
        range(1, len(validated.navigation.stages) + 1)
    )


def _draft_payload() -> dict[str, Any]:
    return {
        "space": {"title": "HTTP provider test"},
        "nodes": [{"temp_id": "foundation", "title": "Foundation"}],
        "edges": [],
    }


def _openai_response() -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"content": json.dumps(_draft_payload())}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


def test_openai_compatible_sends_vision_inputs_as_ephemeral_data_urls() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_openai_response())

    async def invoke() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://openai.test/v1",
                model="vision-model",
                api_key="secret",
                client=client,
            )
            return await provider._chat_json(
                "Describe the learning material",
                vision_inputs=[
                    {
                        "media_type": "image/png",
                        "data_base64": "aW1hZ2U=",
                        "name": "diagram.png",
                    }
                ],
            )

    assert asyncio.run(invoke()) == _draft_payload()
    content = captured["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "Describe the learning material"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
    }


def test_anthropic_sends_vision_inputs_as_image_blocks() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": json.dumps(_draft_payload())}]},
        )

    async def invoke() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(api_key="secret", client=client)
            return await provider._message_json(
                "Describe the learning material",
                vision_inputs=[
                    {
                        "media_type": "image/jpeg",
                        "data_base64": "aW1hZ2U=",
                        "name": "photo.jpg",
                    }
                ],
            )

    assert asyncio.run(invoke()) == _draft_payload()
    content = captured["messages"][0]["content"]
    assert content[0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": "aW1hZ2U=",
        },
    }
    assert content[1] == {"type": "text", "text": "Describe the learning material"}


def test_gemini_sends_vision_inputs_as_inline_data() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(_draft_payload())}]}}]},
        )

    async def invoke() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = GeminiProvider(api_key="secret", client=client)
            return await provider._generate_json(
                "Describe the learning material",
                vision_inputs=[
                    {
                        "media_type": "image/webp",
                        "data_base64": "aW1hZ2U=",
                        "name": "map.webp",
                    }
                ],
            )

    assert asyncio.run(invoke()) == _draft_payload()
    parts = captured["contents"][0]["parts"]
    assert parts[0] == {"inlineData": {"mimeType": "image/webp", "data": "aW1hZ2U="}}
    assert parts[1] == {"text": "Describe the learning material"}


def _learning_plan_payload() -> dict[str, Any]:
    plan = asyncio.run(
        MockProvider().generate_learning_plan(
            "HTTP provider learning plan",
            "Independently deliver a tested practical project",
        )
    )
    return plan.model_dump(mode="json")


def _assert_openai_strict_objects(value: Any) -> None:
    if isinstance(value, list):
        for item in value:
            _assert_openai_strict_objects(item)
        return
    if not isinstance(value, dict):
        return
    assert "default" not in value
    properties = value.get("properties")
    if isinstance(properties, dict):
        assert value.get("additionalProperties") is False
        assert set(value.get("required", [])) == set(properties)
    elif value.get("type") == "object":
        assert value.get("additionalProperties") is False
    for item in value.values():
        _assert_openai_strict_objects(item)


def test_provider_presets_expose_required_catalog_and_editable_defaults() -> None:
    assert set(PROVIDER_PRESETS) == {
        "mock",
        "openai",
        "anthropic",
        "gemini",
        "deepseek",
        "qwen",
        "kimi",
        "zhipu",
        "openrouter",
        "ollama",
        "openai-compatible",
    }
    expected_models = {
        "openai": "gpt-5.6-sol",
        "anthropic": "claude-sonnet-4-5",
        "gemini": "gemini-2.5-flash",
        "deepseek": "deepseek-v4-flash",
        "qwen": "qwen-plus",
        "kimi": "kimi-k2.5",
        "zhipu": "glm-5.2",
        "openrouter": "openai/gpt-5.6",
        "ollama": "qwen3:8b",
    }
    assert {
        name: PROVIDER_PRESETS[name].default_model for name in expected_models
    } == expected_models
    assert PROVIDER_PRESETS["mock"].adapter == "mock"
    assert PROVIDER_PRESETS["anthropic"].adapter == "anthropic"
    assert PROVIDER_PRESETS["gemini"].adapter == "gemini"
    assert PROVIDER_PRESETS["ollama"].adapter == "ollama"
    assert all(PROVIDER_PRESETS[name].requires_key for name in expected_models if name != "ollama")


def test_factory_preserves_legacy_arguments_and_selects_preset_adapters() -> None:
    mock = build_provider(
        "mock",
        base_url="http://unused.test/v1",
        model="legacy-mock",
        api_key=None,
    )
    ollama = build_provider("ollama", base_url=None, model=None, api_key=None)
    anthropic = build_provider("anthropic", api_key="anthropic-secret")
    gemini = build_provider("gemini", api_key="gemini-secret")
    custom = build_provider(
        "openai_compatible",
        base_url="https://custom.test/v1",
        model="custom-model",
        api_key=None,
    )

    assert isinstance(mock, MockProvider)
    assert mock.model == "legacy-mock"
    assert isinstance(ollama, OllamaProvider)
    assert ollama.model == "qwen3:8b"
    assert isinstance(anthropic, AnthropicProvider)
    assert anthropic.model == "claude-sonnet-4-5"
    assert isinstance(gemini, GeminiProvider)
    assert gemini.model == "gemini-2.5-flash"
    assert isinstance(custom, OpenAICompatibleProvider)
    assert custom.name == "openai-compatible"
    assert custom.structured_output == "json_object"


def test_factory_requires_keys_for_remote_named_presets() -> None:
    with pytest.raises(AIProviderError) as exc_info:
        build_provider("openai", api_key=None)

    error = exc_info.value
    assert error.code == "configuration_error"
    assert error.retryable is False
    assert error.status_code is None


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://[::1]:11434/v1",
        "https://provider.example/v1",
    ],
)
def test_provider_transport_accepts_https_or_loopback_http(base_url: str) -> None:
    provider = build_provider(
        "openai_compatible",
        base_url=base_url,
        model="test-model",
        api_key="test-secret",
    )
    assert isinstance(provider, OpenAICompatibleProvider)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://provider.example/v1",
        "http://127.0.0.1.evil.example/v1",
        "https://user:password@provider.example/v1",
        "https://provider.example/v1?secret=value",
        "https://provider.example/v1#fragment",
        "https://provider.example:99999/v1",
    ],
)
def test_provider_transport_rejects_insecure_or_ambiguous_base_urls(base_url: str) -> None:
    with pytest.raises(AIProviderError) as exc_info:
        build_provider(
            "openai_compatible",
            base_url=base_url,
            model="test-model",
            api_key="test-secret",
        )

    assert exc_info.value.code == "configuration_error"


def test_openai_preset_uses_bearer_chat_completions_json_object_and_models() -> None:
    secret = "openai-unit-secret"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert secret not in str(request.url)
        assert request.headers["Authorization"] == f"Bearer {secret}"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})
        body = json.loads(request.content)
        assert request.url.path.endswith("/chat/completions")
        assert body["model"] == "gpt-5.6-sol"
        assert body["response_format"] == {"type": "json_object"}
        assert "JSON must conform to this schema" in body["messages"][0]["content"]
        assert "thinking" not in body
        assert "max_tokens" not in body
        return httpx.Response(200, json=_openai_response())

    async def invoke() -> tuple[str, list[str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = build_provider(
                "openai",
                base_url="https://openai.test/v1",
                model="gpt-5.6-sol",
                api_key=secret,
                client=client,
            )
            draft = await provider.generate_knowledge_map("test source")
            models = await provider.list_models()
            return draft.space.title, models

    title, models = asyncio.run(invoke())
    assert title == "HTTP provider test"
    assert models == ["model-a", "model-b"]
    assert len(requests) == 2


def test_non_openai_compatible_preset_defaults_to_json_object() -> None:
    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json=_openai_response())

    async def invoke() -> tuple[str, str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = build_provider(
                "deepseek",
                base_url="https://deepseek.test/v1",
                model=None,
                api_key="deepseek-secret",
                client=client,
            )
            draft = await provider.generate_knowledge_map("test source")
            return provider.name, draft.space.title

    name, title = asyncio.run(invoke())
    assert name == "deepseek"
    assert title == "HTTP provider test"
    assert captured_body["model"] == "deepseek-v4-flash"
    assert captured_body["response_format"] == {"type": "json_object"}
    assert captured_body["thinking"] == {"type": "disabled"}
    assert captured_body["max_tokens"] == 8192


def test_openai_compatible_generates_learning_plan_with_required_navigation_schema() -> None:
    plan_payload = _learning_plan_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body["response_format"]["json_schema"]["schema"]
        _assert_openai_strict_objects(schema)
        assert "navigation" in schema["required"]
        for name in (
            "GoalSemanticProfileDraft",
            "SemanticStatusLabelsDraft",
            "SemanticActionLabelsDraft",
            "SemanticDimensionLabelsDraft",
        ):
            nested = schema["$defs"][name]
            assert nested["additionalProperties"] is False
            assert set(nested["required"]) == set(nested["properties"])
        assert "user intent JSON" in body["messages"][1]["content"]
        assert "navigation.semantic_profile" in body["messages"][1]["content"]
        assert "presentation vocabulary only" in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(plan_payload)}}]},
        )

    async def invoke() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://openai.test/v1",
                model="test-model",
                api_key="secret",
                client=client,
            )
            plan = await provider.generate_learning_plan("Topic", "Concrete requirements")
            return plan.navigation.target_temp_id

    assert asyncio.run(invoke()) == "capstone"


def test_provider_drops_inverted_semantic_profile_without_losing_valid_plan() -> None:
    plan_payload = _learning_plan_payload()
    plan_payload["navigation"]["semantic_profile"]["status_labels"].update(
        {
            "AVAILABLE": "Do not start",
            "BLOCKED": "Ready now",
            "MASTERED": "Not learned",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(plan_payload)}}]},
        )

    async def invoke() -> LearningPlanDraft:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://openai.test/v1",
                model="test-model",
                api_key="secret",
                client=client,
            )
            return await provider.generate_learning_plan("Topic", "Concrete requirements")

    plan = asyncio.run(invoke())
    assert plan.navigation.semantic_profile is None
    assert plan.navigation.target_temp_id == plan_payload["navigation"]["target_temp_id"]


def test_deepseek_learning_plan_uses_compact_prompt_and_normalizes_edge_mastery() -> None:
    plan_payload = _learning_plan_payload()
    concrete_ids = [
        node["temp_id"] for node in plan_payload["nodes"] if node["node_type"] != "MODULE"
    ]
    for edge in plan_payload["edges"]:
        if edge["relation_type"] != "PREREQUISITE":
            edge["required_mastery_level"] = 4
    plan_payload["edges"].append(
        {
            "source_temp_id": concrete_ids[0],
            "target_temp_id": concrete_ids[-1],
            "relation_type": "RELATED",
            "reason": "Related practical context",
            "confidence": 0.7,
            "required_mastery_level": 5,
        }
    )
    with pytest.raises(ValidationError):
        LearningPlanDraft.model_validate(plan_payload)

    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(plan_payload)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    async def invoke() -> list[tuple[str, int]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = build_provider(
                "deepseek",
                base_url="https://deepseek.test/v1",
                model="deepseek-test-model",
                api_key="deepseek-secret",
                client=client,
            )
            plan = await provider.generate_learning_plan("Topic", "Concrete requirements")
            return [(edge.relation_type.value, edge.required_mastery_level) for edge in plan.edges]

    relations = asyncio.run(invoke())
    assert captured_body["thinking"] == {"type": "disabled"}
    assert captured_body["max_tokens"] == 8192
    prompt = captured_body["messages"][1]["content"]
    assert "exactly 4 top-level MODULE nodes" not in prompt
    assert "1 to 4 concrete" in prompt
    assert "exactly 4 navigation stages" not in prompt
    assert re.search(r"3\s*(?:-|–|to)\s*12", prompt)
    assert re.search(r"3\s*(?:-|–|to)\s*16", prompt)
    assert all(label in prompt.casefold() for label in ("focused", "broad", "multidisciplinary"))
    assert "stage count" in prompt.casefold()
    assert "module count" in prompt.casefold()
    assert "LEARN as a full first-class learning experience" in prompt
    assert all(
        key in prompt
        for key in (
            "AVAILABLE",
            "BLOCKED",
            "MASTERED",
            "IN_PROGRESS",
            "NEEDS_REVIEW",
            "NOT_RELEVANT",
        )
    )
    assert "Every edge whose relation_type is not PREREQUISITE" in prompt
    assert '"relation_type":"CONTAINS"' in prompt
    assert '"required_mastery_level":0' in prompt
    assert all(level == 0 for relation, level in relations if relation != "PREREQUISITE")
    assert all(level >= 1 for relation, level in relations if relation == "PREREQUISITE")
    assert all(
        edge["required_mastery_level"] > 0
        for edge in plan_payload["edges"]
        if edge["relation_type"] != "PREREQUISITE"
    )


def test_deepseek_uses_small_schema_for_a_detailed_explicit_outline() -> None:
    captured_body: dict[str, Any] = {}
    compact_payload = {
        "goal_title": "数学路线",
        "success_definition": "建立数学基础并用于 AI。",
        "target_item_id": "item-03-01",
        "item_profiles": [
            {
                "item_id": "item-01-01",
                "node_type": "CONCEPT",
                "difficulty": 1,
                "description": "数与运算是数学表达和计算的基础。",
                "detailed_description": (
                    "理解数与运算可为函数与梯度下降提供可靠的符号和计算基础，"
                    "并能通过准确完成一组数值运算来验证。"
                ),
            },
            {
                "item_id": "item-02-01",
                "node_type": "CONCEPT",
                "difficulty": 2,
                "description": "函数图像把变量关系转化为可观察的形状。",
                "detailed_description": (
                    "函数图像连接基础运算与后续优化问题，使学习者能够解释输入变化"
                    "如何影响输出并识别基本趋势。"
                ),
            },
            {
                "item_id": "item-03-01",
                "node_type": "SKILL",
                "difficulty": 3,
                "description": "梯度下降是沿局部下降方向迭代优化参数的方法。",
                "detailed_description": (
                    "掌握梯度下降需要联系函数图像理解方向与步长，并能够解释一次"
                    "参数更新为何使目标函数减小。"
                ),
            },
        ],
        "prerequisite_edges": [
            {
                "source_item_id": "item-01-01",
                "target_item_id": "item-02-01",
                "reason": "基础先于函数。",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(compact_payload)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    requirements = """第一阶段：基础
包括：
* 数与运算
第二阶段：函数
包括：
* 函数图像
第三阶段：应用
包括：
* 梯度下降"""

    async def invoke() -> LearningPlanDraft:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = build_provider(
                "deepseek",
                base_url="https://deepseek.test/v1",
                model="deepseek-test-model",
                api_key="deepseek-secret",
                client=client,
            )
            return await provider.generate_learning_plan("数学", requirements)

    plan = asyncio.run(invoke())
    schema_text = captured_body["messages"][0]["content"]
    prompt = captured_body["messages"][1]["content"]
    assert "CompactExplicitPlanDraft" in schema_text
    assert "The application will preserve all user titles" in prompt
    assert "derive description and detailed_description" in prompt
    assert "detailed_description must not merely repeat description" in prompt
    assert [stage.title for stage in plan.navigation.stages] == ["基础", "函数", "应用"]
    assert sum(len(stage.node_temp_ids) for stage in plan.navigation.stages) == 3
    assert len([edge for edge in plan.edges if edge.relation_type.value == "CONTAINS"]) == 3
    concrete = [node for node in plan.nodes if node.node_type.value != "MODULE"]
    assert all(node.description and node.detailed_description for node in concrete)
    assert all(node.source_basis == ["用户提供的长文本大纲"] for node in concrete)


def test_collaboration_normalizes_only_safe_plan_metadata_before_validation() -> None:
    plan_payload = _learning_plan_payload()
    plan_payload["navigation"]["semantic_profile"]["status_labels"]["AVAILABLE"] = "模型自定义状态"
    for edge in plan_payload["edges"]:
        if edge["relation_type"] != "PREREQUISITE":
            edge["required_mastery_level"] = 5
    raw = {
        "message": "方案草稿已更新",
        "tool_calls": [],
        "working_plan": plan_payload,
        "plan_ready": True,
    }

    with pytest.raises(ValidationError):
        CollaborationAIResponse.model_validate(raw)

    normalized = _normalize_collaboration_payload(raw)
    response = CollaborationAIResponse.model_validate(normalized)

    assert response.working_plan is not None
    assert response.working_plan.navigation.semantic_profile is None
    assert all(
        edge.required_mastery_level == 0
        for edge in response.working_plan.edges
        if edge.relation_type.value != "PREREQUISITE"
    )
    assert raw["working_plan"] is plan_payload


def test_anthropic_uses_native_headers_messages_and_model_listing() -> None:
    secret = "anthropic-unit-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert secret not in str(request.url)
        assert request.headers["x-api-key"] == secret
        assert request.headers["anthropic-version"] == "2023-06-01"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "claude-a"}]})
        body = json.loads(request.content)
        assert request.url.path.endswith("/messages")
        assert body["model"] == "claude-sonnet-4-5"
        assert body["messages"][0]["role"] == "user"
        assert "JSON must conform to this schema" in body["system"]
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": json.dumps(_draft_payload())}]},
        )

    async def invoke() -> tuple[str, list[str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(api_key=secret, client=client)
            draft = await provider.generate_knowledge_map("test source")
            return draft.space.title, await provider.list_models()

    title, models = asyncio.run(invoke())
    assert title == "HTTP provider test"
    assert models == ["claude-a"]


def test_anthropic_generates_learning_plan_in_one_structured_message() -> None:
    plan_payload = _learning_plan_payload()
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        body = json.loads(request.content)
        assert '"navigation"' in body["system"]
        assert "user intent JSON" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": json.dumps(plan_payload)}]},
        )

    async def invoke() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(api_key="secret", client=client)
            plan = await provider.generate_learning_plan("Topic", "Concrete requirements")
            return len(plan.navigation.stages)

    assert asyncio.run(invoke()) == 4
    assert request_count == 1


def test_gemini_uses_header_generate_content_json_mode_and_model_listing() -> None:
    secret = "gemini-unit-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert secret not in str(request.url)
        assert request.headers["x-goog-api-key"] == secret
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"models": [{"name": "models/gemini-a"}, {"name": "models/gemini-b"}]},
            )
        body = json.loads(request.content)
        assert request.url.path.endswith("/models/gemini-2.5-flash:generateContent")
        assert body["contents"][0]["role"] == "user"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseJsonSchema" in body["generationConfig"]
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(_draft_payload())}]}}]},
        )

    async def invoke() -> tuple[str, list[str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = GeminiProvider(api_key=secret, client=client)
            draft = await provider.generate_knowledge_map("test source")
            return draft.space.title, await provider.list_models()

    title, models = asyncio.run(invoke())
    assert title == "HTTP provider test"
    assert models == ["gemini-a", "gemini-b"]


def test_gemini_generates_learning_plan_in_one_json_generate_content_call() -> None:
    plan_payload = _learning_plan_payload()
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]
        assert "navigation" in schema["required"]
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(plan_payload)}]}}]},
        )

    async def invoke() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = GeminiProvider(api_key="secret", client=client)
            plan = await provider.generate_learning_plan("Topic", "Concrete requirements")
            return plan.navigation.target_mastery_level

    assert asyncio.run(invoke()) == 4
    assert request_count == 1


@pytest.mark.parametrize(
    ("status", "expected_code", "retryable"),
    [
        (401, "authentication_error", False),
        (403, "authentication_error", False),
        (429, "rate_limit_error", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
        (400, "request_error", False),
    ],
)
def test_http_status_errors_are_typed_and_redacted(
    status: int, expected_code: str, retryable: bool
) -> None:
    secret = "never-leak-this-key"
    upstream_secret = "sensitive-upstream-body"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=upstream_secret)

    async def invoke() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://provider.test/v1",
                model="test-model",
                api_key=secret,
                client=client,
            )
            await provider.list_models()

    with pytest.raises(AIProviderError) as exc_info:
        asyncio.run(invoke())
    error = exc_info.value
    assert error.code == expected_code
    assert error.retryable is retryable
    assert error.status_code == status
    assert secret not in str(error)
    assert upstream_secret not in str(error)
    assert secret not in repr(error)


@pytest.mark.parametrize(
    ("exception_factory", "expected_code"),
    [
        (
            lambda request: httpx.ReadTimeout("unsafe timeout detail", request=request),
            "timeout_error",
        ),
        (
            lambda request: httpx.ConnectError("unsafe connection detail", request=request),
            "connection_error",
        ),
    ],
)
def test_transport_errors_are_retryable_and_redacted(
    exception_factory: Callable[[httpx.Request], httpx.RequestError], expected_code: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_factory(request)

    async def invoke() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://provider.test/v1",
                model="test-model",
                api_key="secret-key",
                client=client,
            )
            await provider.list_models()

    with pytest.raises(AIProviderError) as exc_info:
        asyncio.run(invoke())
    error = exc_info.value
    assert error.code == expected_code
    assert error.retryable is True
    assert error.status_code is None
    assert "unsafe" not in str(error)
    assert "secret-key" not in str(error)


@pytest.mark.parametrize(
    ("finish_reason", "expected_message", "expected_code", "retryable"),
    [
        ("length", "AI provider response was truncated", "invalid_response", True),
        ("content_filter", "AI provider blocked the response", "request_error", False),
        (
            "insufficient_system_resource",
            "AI provider lacked resources to complete the response",
            "upstream_error",
            True,
        ),
    ],
)
def test_incomplete_finish_reasons_use_specific_safe_provider_errors(
    finish_reason: str,
    expected_message: str,
    expected_code: str,
    retryable: bool,
) -> None:
    sensitive_content = "private learner input and https://secret.internal/resource"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": sensitive_content},
                        "finish_reason": finish_reason,
                    }
                ]
            },
        )

    async def invoke() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://provider.test/v1",
                model="test-model",
                api_key="secret-key",
                client=client,
            )
            await provider.generate_learning_plan("Topic", "Requirements")

    with pytest.raises(AIProviderError) as exc_info:
        asyncio.run(invoke())
    error = exc_info.value
    assert str(error) == expected_message
    assert error.code == expected_code
    assert error.retryable is retryable
    assert error.status_code is None
    assert sensitive_content not in str(error)
    assert sensitive_content not in repr(error)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}),
    ],
)
def test_malformed_or_invalid_response_shapes_use_safe_provider_error(
    response: httpx.Response,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    async def invoke() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://provider.test/v1",
                model="test-model",
                api_key="secret-key",
                client=client,
            )
            await provider.generate_knowledge_map("test source")

    with pytest.raises(AIProviderError) as exc_info:
        asyncio.run(invoke())
    error = exc_info.value
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert "secret-key" not in str(error)


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "ftp://provider.test/v1",
        "https://user:password@provider.test/v1",
        "https://provider.test/v1?api_key=secret",
    ],
)
def test_base_url_rejects_credentials_queries_and_unsafe_schemes(base_url: str) -> None:
    with pytest.raises(AIProviderError) as exc_info:
        OpenAICompatibleProvider(base_url=base_url, model="test-model", api_key="secret")

    assert exc_info.value.code == "configuration_error"
    assert "secret" not in str(exc_info.value)
