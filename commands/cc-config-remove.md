---
description: 删除一个模型映射别名
---

用户输入格式为 `/cc-config-remove <别名>`，请从用户消息中提取别名参数。

执行命令：`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" remove <别名>`

如果用户没有提供参数，先执行 `list` 展示当前映射，让用户确认要删除哪一个。
