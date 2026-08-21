#!/usr/bin/env python3
"""ccds-bridge 统计面板：简洁展示当前会话的核心指标。

设计原则：用户一眼看懂——缓存好不好、额度剩多少、有没有异常。
"""
import glob
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("CCDS_BRIDGE_HOME", os.path.expanduser("~/.ccds-bridge"))
SESSION_STATS = os.path.join(BASE, "session_stats.json")
ACTIVE_SESSION_FILE = os.path.join(BASE, "active_session.json")
ACTIVE_SESSION_MAX_AGE = 600


def fmt_num(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "0"
    if n >= 1e6:
        return "%.1fM" % (n / 1e6)
    if n >= 1e3:
        return "%.0fK" % (n / 1e3)
    return "%.0f" % n


def hit_rate_label(pct):
    """缓存命中率的直观描述。"""
    if pct >= 90:
        return "优秀"
    if pct >= 70:
        return "良好"
    if pct >= 40:
        return "一般"
    if pct > 0:
        return "偏低"
    return "无缓存"


def latest_session_id():
    try:
        with open(ACTIVE_SESSION_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        sid = data.get("session_id")
        if sid and time.time() - float(data.get("ts") or 0) < ACTIVE_SESSION_MAX_AGE:
            return sid
    except Exception:
        pass
    files = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    if not files:
        return None
    latest = max(files, key=os.path.getmtime)
    return os.path.basename(latest)[:-6]


def query_provider_balance():
    threep_glob = (
        os.path.expandvars(r"%APPDATA%\Claude-3p\configLibrary\*.json")
        if os.name == "nt"
        else os.path.expanduser("~/Library/Application Support/Claude-3p/configLibrary/*.json")
    )
    paths = glob.glob(threep_glob)
    real_key = None
    for p in paths:
        try:
            d = json.load(open(p, encoding="utf-8"))
            if d.get("inferenceGatewayApiKey"):
                real_key = d["inferenceGatewayApiKey"]
                break
        except Exception:
            pass
    if not real_key:
        return None

    # OpenCode 额度
    try:
        url = "https://opencode.ai/zen/go/v1/usage"
        headers = {
            "Authorization": "Bearer %s" % real_key,
            "x-api-key": real_key,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("usage"):
                return ("opencode", data["usage"])
    except Exception:
        pass

    # DeepSeek 余额
    try:
        url = "https://api.deepseek.com/user/balance"
        headers = {
            "Authorization": "Bearer %s" % real_key,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("balance_infos"):
                return ("deepseek", data["balance_infos"])
    except Exception:
        pass

    return None


def main():
    if "--session" in sys.argv:
        idx = sys.argv.index("--session")
        sid = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""
    else:
        sid = latest_session_id()

    try:
        data = json.load(open(SESSION_STATS, encoding="utf-8"))
    except Exception:
        data = {}

    hits = [(k, v) for k, v in data.items() if k.startswith(sid or "")]
    if not hits:
        print("未检测到当前会话（网关刚启动或该会话尚无请求）")
        return

    for k, s in hits:
        rec = s.get("recent") or []
        total_in = s.get("input_tokens", 0) + s.get("cache_read", 0)
        overall_pct = (s.get("cache_read", 0) / total_in * 100) if total_in > 0 else 0

        # 最近 5 轮平均命中率
        recent_5 = rec[-5:] if len(rec) >= 5 else rec
        recent_in = sum(r.get("in", 0) + r.get("cr", 0) for r in recent_5)
        recent_cr = sum(r.get("cr", 0) for r in recent_5)
        recent_pct = (recent_cr / recent_in * 100) if recent_in > 0 else 0

        # 趋势箭头（累计 vs 最近5轮）
        if recent_pct > overall_pct + 5:
            trend = "↗"
        elif recent_pct < overall_pct - 5:
            trend = "↘"
        else:
            trend = "→"

        # 上下文大小 & 请求统计
        ctx = s.get("last_cr", 0)
        upstream = s.get("upstream", 0)
        probe = s.get("probe", 0)

        # ── 标题 ──
        print("======================================================")
        print(" 会话: %s" % (k[:20] + "..." if len(k) > 20 else k))
        print("------------------------------------------------------")

        # ── 缓存命中 ──
        if overall_pct > 0:
            label = hit_rate_label(overall_pct)
            if recent_in > 0:
                print(" 缓存命中: %.0f%%（%s）· 近5轮: %.0f%% %s"
                      % (overall_pct, label, recent_pct, trend))
            else:
                print(" 缓存命中: %.0f%%（%s）" % (overall_pct, label))
        else:
            print(" 缓存命中: 暂无数据")

        # ── 上下文 & 请求 ──
        print(" 上下文: %s · 请求: %d 次（上游 %d · 本地拦截 %d）"
              % (fmt_num(ctx), upstream + probe, upstream, probe))

        # ── 主/子代理分类 ──
        kinds = s.get("kinds") or {}
        main_k = kinds.get("main", {})
        sub_k = kinds.get("subagent", {})
        main_r = main_k.get("upstream", 0)
        sub_r = sub_k.get("upstream", 0)
        if main_r > 0 or sub_r > 0:
            parts = []
            if main_r > 0:
                parts.append("主对话 %d" % main_r)
            if sub_r > 0:
                parts.append("子代理 %d" % sub_r)
            print(" 分类:     %s" % " · ".join(parts))

        # ── 异常事件 ──
        kinds = s.get("kinds") or {}
        all_drops = []
        for kind_data in kinds.values():
            all_drops.extend(kind_data.get("drops") or [])
        if all_drops:
            last_drop = all_drops[-1]
            print(" ⚠ 缓存掉落 %d 次（最近: %s, cr %s→%s, %s）"
                  % (len(all_drops), last_drop["ts"][5:16],
                     fmt_num(last_drop["prev_cr"]), fmt_num(last_drop["cr"]),
                     last_drop.get("cause", "")))
        else:
            print(" 异常: 无")

        print("------------------------------------------------------")

        # ── 供应商额度 ──
        provider_data = query_provider_balance()
        if provider_data:
            prov_type, prov_info = provider_data
            if prov_type == "opencode":
                rolling = prov_info.get("rolling", {}).get("percent", 0)
                weekly = prov_info.get("weekly", {}).get("percent", 0)
                monthly = prov_info.get("monthly", {}).get("percent", 0)
                print(" OpenCode: 5h %d%% · 周 %d%% · 月 %d%%"
                      % (rolling, weekly, monthly))
            elif prov_type == "deepseek":
                for b in prov_info:
                    curr = b.get("currency", "CNY")
                    tot = b.get("total_balance", "0.00")
                    print(" DeepSeek: 余额 %s %s" % (tot, curr))

        print("======================================================")


if __name__ == "__main__":
    main()
