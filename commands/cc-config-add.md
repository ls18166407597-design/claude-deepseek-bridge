---
description: 添加或更新一个模型映射（格式：别名 目标模型）
---

用户输入格式为 `/cc-config-add <别名> <目标模型>`，请从用户消息中提取这两个参数。

示例：`/cc-config-add claude-qwen qwen-max`

执行命令：`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" add <别名> <目标模型>`

如果用户没有提供参数，请提示格式：`/cc-config-add <3P界面填写的Model ID> <真实上游模型名>`
