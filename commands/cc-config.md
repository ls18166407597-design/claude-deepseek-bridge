---
description: 管理模型映射配置（添加/删除/查看模型别名）
---

请执行命令 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" list` 查看当前所有模型映射，并将结果清晰地展示给用户。

支持的子命令（用户可直接说自然语言，你来翻译成对应命令）：
- **查看所有映射**：`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" list`
- **添加映射**：`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" add <别名> <目标模型>`
- **删除映射**：`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" remove <别名>`
- **恢复默认**：`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" reset`

映射格式：别名（3P 界面填的 Model ID）→ 目标模型（真实上游模型名，如 deepseek-v4-flash）。
修改后立即生效，本地插件下次请求时自动读取新配置，无需重启。
