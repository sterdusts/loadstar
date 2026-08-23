"""UI contracts for local-first AI conversation attachments."""

from __future__ import annotations

import inspect

from learning_navigator.ui.components import global_ai_assistant, layout


def test_global_assistant_supports_unbounded_batch_uploads_paste_and_path_generation() -> None:
    panel_source = inspect.getsource(global_ai_assistant.mount_global_ai_assistant)
    module_source = inspect.getsource(global_ai_assistant)
    css_source = inspect.getsource(layout.install_theme)

    assert "ATTACHMENT_PATH_PROMPT" in module_source
    assert "_AI_ATTACHMENT_PASTE_BOOTSTRAP" in module_source
    assert "document.addEventListener('paste'" in module_source
    assert '"/ai/attachments"' in panel_source
    assert '"attachment_ids": attachment_ids' in panel_source
    assert "multiple=True" in panel_source
    assert "on_multi_upload=finish_attachment_upload" in panel_source
    assert "max_file_size" not in panel_source
    assert '"依据附件生成路径"' in panel_source
    assert "ln-ai-staged-attachments" in panel_source
    assert 'ui.notify(f"已在本地保存' not in panel_source
    assert ".ln-ai-staged-attachments" in css_source
    assert ".ln-ai-message-attachment" in css_source
