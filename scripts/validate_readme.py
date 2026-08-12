"""Validate the single-file bilingual README contract."""

from __future__ import annotations

import re
from pathlib import Path


def main() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert text.count('<a id="english"></a>') == 1
    assert text.count('<a id="简体中文"></a>') == 1
    assert "[English](#english)" in text
    assert "[简体中文](#简体中文)" in text
    assert "[切换到简体中文 ↓](#简体中文)" in text
    assert "[Switch to English ↑](#english)" in text

    missing_links: list[str] = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#")):
            continue
        relative_path = target.split("#", maxsplit=1)[0]
        if relative_path and not (readme.parent / relative_path).exists():
            missing_links.append(relative_path)
    assert not missing_links, f"Missing local README links: {missing_links}"

    english, chinese = text.split('<a id="简体中文"></a>', maxsplit=1)
    assert all(
        heading in english
        for heading in (
            "### Quick Start",
            "### Installation and Launch",
            "### AI Connections and Offline Use",
            "### Quality Checks",
            "### License",
        )
    )
    assert all(
        heading in chinese
        for heading in (
            "## 最快使用",
            "## 安装与启动",
            "## AI 连接与离线体验",
            "## 质量检查",
            "## License",
        )
    )

    print("README bilingual navigation and local links are valid.")


if __name__ == "__main__":
    main()
