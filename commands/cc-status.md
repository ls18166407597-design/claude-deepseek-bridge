---
description: 查看当前会话的缓存状态与 Token 节省统计（主对话/子代理独立展示）
---

请执行命令 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stats.py"` 查询当前会话的运行指标与缓存命中率，并将脚本输出的统计面板原样展示给用户。

如果提示网关未运行，请提示用户运行 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manager.py" start` 重新拉起网关。
