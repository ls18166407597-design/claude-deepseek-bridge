#!/usr/bin/env python3
"""ccds-bridge 模型映射配置管理脚本。

用法（供斜杠命令调用）：
  python3 config.py list                    — 列出所有模型映射
  python3 config.py add <alias> <target>    — 添加/覆盖一个映射
  python3 config.py remove <alias>          — 删除一个映射别名
  python3 config.py reset                   — 删除用户配置，回退到网关内置默认值
"""
import json
import os
import sys

BASE_DIR = os.environ.get("CCDS_BRIDGE_HOME", os.path.expanduser("~/.ccds-bridge"))
MODELS_FILE = os.path.join(BASE_DIR, "models.json")


def load():
    """读取用户配置；文件不存在或为空时返回空 dict（网关自行兜底默认值）。"""
    try:
        with open(MODELS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save(mapping):
    os.makedirs(BASE_DIR, exist_ok=True)
    tmp = MODELS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, MODELS_FILE)


def cmd_list():
    mapping = load()
    if not mapping:
        print("用户未配置模型映射，网关使用内置默认值（详见 gateway.py MODELS_DEFAULTS）。")
        print(f"可通过 /cc-config-add <Claude Model ID> <真实模型名> 添加自定义映射。")
        print(f"配置文件：{MODELS_FILE}（不存在）")
        return
    # 按上游模型分组展示
    groups = {}
    for alias, target in sorted(mapping.items()):
        groups.setdefault(target, []).append(alias)
    print("当前模型映射：\n")
    for target in sorted(groups):
        aliases = groups[target]
        print(f"  {target}")
        for a in aliases:
            print(f"    └─ {a}")
    print(f"\n共 {len(mapping)} 条别名，映射到 {len(groups)} 个上游模型")
    print(f"配置文件：{MODELS_FILE}")


def cmd_add(alias, target):
    if not alias or not target:
        print("用法：config.py add <别名> <目标模型>")
        print("例如：config.py add claude-sonnet-5 deepseek-v4-flash")
        return
    mapping = load()
    old = mapping.get(alias)
    mapping[alias.lower()] = target.lower()
    save(mapping)
    if old:
        print(f"已更新：{alias} → {target}（原值：{old}）")
    else:
        print(f"已添加：{alias} → {target}")
    print("本地插件下次请求时自动生效（无需重启）。")


def cmd_remove(alias):
    if not alias:
        print("用法：config.py remove <别名>")
        return
    mapping = load()
    key = alias.lower()
    if key not in mapping:
        print(f"未找到别名：{alias}")
        return
    old = mapping.pop(key)
    if mapping:
        save(mapping)
    else:
        # 最后一条也删掉了，直接删除文件，让网关回退到内置默认值
        try:
            os.remove(MODELS_FILE)
        except OSError:
            pass
    print(f"已删除：{alias}（原映射：{old}）")


def cmd_reset():
    """删除用户配置文件，网关下次请求自动回退到内置默认值。"""
    try:
        os.remove(MODELS_FILE)
        print("已删除用户配置，网关已回退到内置默认值。")
    except FileNotFoundError:
        print("用户配置不存在，网关已在使用内置默认值。")
    print(f"配置文件：{MODELS_FILE}（已删除）")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "list":
        cmd_list()
    elif args[0] == "add" and len(args) >= 3:
        cmd_add(args[1], args[2])
    elif args[0] == "remove" and len(args) >= 2:
        cmd_remove(args[1])
    elif args[0] == "reset":
        cmd_reset()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
