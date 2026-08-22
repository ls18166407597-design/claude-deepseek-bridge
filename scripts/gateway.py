#!/usr/bin/env python3
"""Claude Desktop 3P gateway -> OpenCode Go DeepSeek model-name rewrite proxy."""
import glob
import json
import os
import re
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT_PREFERRED = int(os.environ.get("GATEWAY_PORT", "8789"))
PORT_SCAN_LIMIT = 20
BASE_DIR = os.environ.get("CCDS_BRIDGE_HOME", os.path.expanduser("~/.ccds-bridge"))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATS_FILE = os.path.join(BASE_DIR, "stats.json")
SESSION_STATS_FILE = os.path.join(BASE_DIR, "session_stats.json")
BILLING_HEADER_PIN = "x-anthropic-billing-header: cc_version=2.1.229; cc_entrypoint=claude-desktop-3p;"
BILLING_HEADER_PIN_SUBAGENT = BILLING_HEADER_PIN + " cc_is_subagent=true;"
SESSION_DATES_FILE = os.environ.get("SESSION_DATES_FILE", os.path.join(BASE_DIR, "session_dates.json"))
ACTIVE_SESSION_FILE = os.path.join(BASE_DIR, "active_session.json")
PROJECTS_DIR = os.environ.get("CLAUDE_PROJECTS_DIR", os.path.expanduser("~/.claude/projects"))
DATE_RE = re.compile(r"Today's date is (\d{4}-\d{2}-\d{2})\.")
LOG_MAX_BYTES = 5 * 1024 * 1024
STATS_SAVE_INTERVAL = 10  # 统计落盘最小间隔（秒）：批量化，避免每请求多次全量原子写
MAX_SESSIONS = 300  # session_stats 会话条目上限，防文件无限增长

MODELS_CONFIG_FILE = os.path.join(BASE_DIR, "models.json")
_cached_models = None
MODELS_CONFIG_MTIME = 0.0  # 用于热加载检测

MODELS_DEFAULTS = {
    "claude-opus-5":     "deepseek-v4-pro",
    "claude-opus":       "deepseek-v4-pro",
    "claude-sonnet-5":   "deepseek-v4-flash",
    "claude-sonnet":     "deepseek-v4-flash",
    "claude-opus-4-6":   "mimo-v2.5-pro",
    "claude-xiaomi-pro": "mimo-v2.5-pro",
    "claude-sonnet-4-6": "mimo-v2.5",
    "claude-xiaomi":     "mimo-v2.5",
}


def read_models_config():
    """读取 models.json，文件不存在或解析失败时退回硬编码默认值。"""
    global MODELS_CONFIG_MTIME, _cached_models
    try:
        mtime = os.path.getmtime(MODELS_CONFIG_FILE)
        if _cached_models is None or mtime != MODELS_CONFIG_MTIME:
            MODELS_CONFIG_MTIME = mtime
            with open(MODELS_CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data:
                _cached_models = data
        if _cached_models:
            return dict(_cached_models)
    except (OSError, json.JSONDecodeError, ValueError):
        MODELS_CONFIG_MTIME = 0.0
        _cached_models = None
    return dict(MODELS_DEFAULTS)


def write_models_config(mapping):
    """将模型映射写入 models.json（原子写）。"""
    global MODELS_CONFIG_MTIME
    os.makedirs(BASE_DIR, exist_ok=True)
    tmp = MODELS_CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, MODELS_CONFIG_FILE)
    MODELS_CONFIG_MTIME = os.path.getmtime(MODELS_CONFIG_FILE)


# 启动时加载一次，运行中按 mtime 自动热加载
_models = read_models_config()
MODEL_LIST = sorted(_models.keys())


def normalize_upstream(url):
    """上游必须是完整 /v1/messages 端点；3P base URL 缺后缀时自动补全。"""
    url = (url or "").strip().rstrip("/")
    if url and not url.endswith("/v1/messages"):
        url += "/v1/messages"
    return url


_upstream_cache = None
_upstream_mtime = 0.0


def load_upstream():
    global _upstream_cache, _upstream_mtime
    try:
        mtime = os.path.getmtime(CONFIG_FILE)
        if _upstream_cache is not None and mtime == _upstream_mtime:
            return _upstream_cache
        _upstream_mtime = mtime
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        url = (cfg.get("upstream_url") or "").strip()
        _upstream_cache = normalize_upstream(url) if url else None
        return _upstream_cache
    except OSError:
        _upstream_mtime = 0.0
        _upstream_cache = None
        return None


CACHE_STABILIZE = os.environ.get("CACHE_STABILIZE", os.environ.get("CCDS_CACHE_STABILIZE", "1")) != "0"


_stats = {
    "requests": 0,
    "probe_local": 0,
    "date_pin": 0,
    "billing_pin": 0,
    "user_content_shape": 0,
    "upstream_ok": 0,
    "http_errors": 0,
    "input_tokens": 0,
    "cache_read": 0,
    "output_tokens": 0,
}
_stats_lock = threading.Lock()
_stats_save_ts = 0.0
_cleanup_counter = 0
_session_stats = {}
_session_stats_lock = threading.Lock()
_session_stats_save_ts = 0.0
_last_active_sid = None


def load_session_stats():
    global _session_stats
    try:
        with open(SESSION_STATS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            # 子代理并发混流时相邻请求的 cr 交替跳变不是真正掉落，
            # 只保留空闲超过 1h 的掉落记录（gap_h >= 1 才算真实掉落）
            for s in data.values():
                sub = (s.get("kinds") or {}).get("subagent")
                if sub:
                    sub["drops"] = [
                        d for d in (sub.get("drops") or []) if (d.get("gap_h") or 0) >= 1
                    ]
            _session_stats = data
    except OSError:
        pass


def save_session_stats():
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        tmp = SESSION_STATS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_session_stats, fh, ensure_ascii=False)
        os.replace(tmp, SESSION_STATS_FILE)
    except OSError:
        pass


def prune_session_stats():
    """会话条目有界：只保留最近活跃的 N 个会话（按首次出现时间），防止文件无限增长。"""
    if len(_session_stats) <= MAX_SESSIONS:
        return
    keep = sorted(
        _session_stats.items(),
        key=lambda kv: kv[1].get("first_ts") or 0,
    )[-MAX_SESSIONS:]
    _session_stats.clear()
    _session_stats.update(dict(keep))


def touch_active_session(sid):
    """记录最近活跃会话，供 /ccds-status 识别「当前会话」。

    多会话并存时按 transcript mtime 猜测会认错会话；网关看到的每个真实请求
    （含探测）都带会话 ID，以此为准。只在会话变化时落盘，代价可忽略。
    """
    global _last_active_sid
    if not sid or sid == _last_active_sid:
        return
    _last_active_sid = sid
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        tmp = ACTIVE_SESSION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"session_id": sid, "ts": time.time()}, fh)
        os.replace(tmp, ACTIVE_SESSION_FILE)
    except OSError:
        pass


def record_session(sid, event, messages=0, usage=None, kind="main"):
    """按会话 + 主/子代理类型记录轻量统计，并分别检测缓存掉落事件。"""
    global _session_stats_save_ts
    if not sid:
        return
    now = time.time()
    with _session_stats_lock:
        s = _session_stats.setdefault(sid, {
            "requests": 0, "upstream": 0, "probe": 0,
            "input_tokens": 0, "cache_read": 0, "output_tokens": 0,
            "first_ts": now, "last_ts": None, "last_cr": 0,
            "recent": [], "drops": [],
        })
        # 旧版本数据没有 kinds：把历史汇总归入 main（尽力恢复，子代理部分无法追溯）
        if "kinds" not in s:
            s["kinds"] = {}
        if "main" not in s["kinds"]:
            s["kinds"]["main"] = {
                "requests": s.get("requests", 0), "upstream": s.get("upstream", 0),
                "probe": s.get("probe", 0), "input_tokens": s.get("input_tokens", 0),
                "cache_read": s.get("cache_read", 0), "output_tokens": s.get("output_tokens", 0),
                "first_ts": s.get("first_ts", now), "last_cr": s.get("last_cr", 0),
                "recent": list(s.get("recent", [])), "drops": list(s.get("drops", [])),
            }
        k = s["kinds"].setdefault(kind, {
            "requests": 0, "upstream": 0, "probe": 0,
            "input_tokens": 0, "cache_read": 0, "output_tokens": 0,
            "first_ts": now, "last_cr": 0, "recent": [], "drops": [],
        })
        s["requests"] += 1
        k["requests"] += 1
        if event == "probe_local":
            s["probe"] += 1
            k["probe"] += 1
        elif event == "upstream_ok" and usage:
            s["upstream"] += 1
            k["upstream"] += 1
            inp = usage.get("input_tokens") or 0
            cr = usage.get("cache_read_input_tokens") or 0
            out = usage.get("output_tokens") or 0
            s["input_tokens"] += inp
            s["cache_read"] += cr
            s["output_tokens"] += out
            k["input_tokens"] += inp
            k["cache_read"] += cr
            k["output_tokens"] += out
            prev_cr = k.get("last_cr") or 0
            # 主/子代理各自维护独立上下文，掉落检测必须按类型分开，否则会互相误报。
            # 间隔取「同类上一次请求」的时间（recent 最后一条），而不是会话全局时间。
            prev_ts_k = k["recent"][-1]["ts"] if k["recent"] else None
            gap = (now - prev_ts_k) / 3600 if prev_ts_k else 0
            # 子代理无个体标识：同一 session_id 下多个并发子代理混在同一桶里，
            # 相邻请求的 cr 交替跳变是并发混流而非掉落（实测 3 条 gap≈0 的
            # 「掉落」均为混流误报）。只判定空闲 >1h 形态的回落——那才是
            # 真正关心的场景（子代理空闲恢复重算）。
            if kind == "subagent":
                is_drop = (
                    gap >= 1 and messages >= 2 and prev_cr > 10000 and cr < prev_cr
                )
                cause = "空闲恢复（>1h）"
            else:
                # 只要 cr 比上一次低就是掉落（压缩重置已在上游由 is_compaction 放行）
                is_drop = prev_cr > 0 and cr < prev_cr
                cause = "空闲/TTL过期" if gap >= 1 else "前缀变化/异常"
            if is_drop:
                drop = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "prev_cr": prev_cr,
                    "cr": cr,
                    "gap_h": round(gap, 2),
                    "cause": cause,
                }
                k["drops"].append(drop)
                k["drops"] = k["drops"][-20:]
                if kind == "main":
                    s["drops"].append(drop)
                    s["drops"] = s["drops"][-20:]
            k["last_cr"] = cr
            k["recent"].append({"ts": now, "in": inp, "cr": cr})
            k["recent"] = k["recent"][-50:]
            if kind == "main":
                s["last_cr"] = cr
                s["recent"].append({"ts": now, "in": inp, "cr": cr})
                s["recent"] = s["recent"][-50:]
        s["last_ts"] = now
        # 批量化落盘：session_stats 按请求全量重写成本高，10 秒最多写一次
        if now - _session_stats_save_ts >= STATS_SAVE_INTERVAL:
            _session_stats_save_ts = now
            prune_session_stats()
            save_session_stats()


def cleanup_runtime():
    """轮转网关日志。"""
    global _cleanup_counter
    log_path = os.path.join(BASE_DIR, "logs", "gateway.log")
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > LOG_MAX_BYTES:
            os.replace(log_path, log_path + ".old")
    except OSError:
        pass
    _cleanup_counter = 0


def bump_stats(**kwargs):
    global _cleanup_counter, _stats_save_ts
    with _stats_lock:
        for key, value in kwargs.items():
            _stats[key] = _stats.get(key, 0) + value
        # 批量化落盘：此前每个事件一次全量原子写（每请求最多 6 次），10 秒最多写一次
        now = time.time()
        if now - _stats_save_ts >= STATS_SAVE_INTERVAL:
            _stats_save_ts = now
            try:
                os.makedirs(BASE_DIR, exist_ok=True)
                tmp = STATS_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(_stats, fh, ensure_ascii=False, indent=1)
                os.replace(tmp, STATS_FILE)
            except OSError:
                pass
    _cleanup_counter += 1
    if _cleanup_counter >= 500:
        cleanup_runtime()


def client_api_key(headers):
    x = headers.get("x-api-key") or headers.get("X-Api-Key")
    if x:
        return x.strip()
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def extract_session_id(parsed):
    """Session ID is carried inside metadata.user_id as a JSON string."""
    try:
        uid = (parsed.get("metadata") or {}).get("user_id") or ""
        if isinstance(uid, str) and uid.strip().startswith("{"):
            return json.loads(uid).get("session_id") or ""
    except Exception:
        pass
    return ""


def map_model(model):
    """直接字典查找：自动剥离 [1m] 等上下文后缀并从 models.json 获取真实映射。"""
    global _models
    _models = read_models_config()
    raw = (model or "").strip()
    clean = re.sub(r"\[.*?\]$", "", raw).strip().lower()
    return _models.get(clean) or _models.get(raw.lower()) or raw or "deepseek-v4-flash"


def log_event(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def count_cache_control(obj):
    count = 0
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "cache_control":
                count += 1
            count += count_cache_control(value)
    elif isinstance(obj, list):
        for item in obj:
            count += count_cache_control(item)
    return count


def is_probe_request(parsed):
    """Claude Code/Desktop capability and token-counting probes."""
    if parsed.get("max_tokens") != 1:
        return False
    if parsed.get("stream"):
        return False
    msgs = parsed.get("messages") or []
    return len(msgs) == 1 and isinstance(msgs[0], dict) and msgs[0].get("role") == "user"


def estimate_tokens(obj):
    def walk(x):
        if isinstance(x, str):
            # 智能识别 Base64 图像字符串（如 JPEG / PNG / Data URL），按视觉标准（~1600 tokens）计算
            if len(x) > 500 and (x.startswith("/9j/") or x.startswith("iVBORw") or "data:image/" in x[:30]):
                return 1600
            # 拟合真实混合 BPE 切词器：中文字符约 0.65 tokens，英文/代码/JSON 字符约 1/3.4 tokens
            cn_count = sum(1 for c in x if "\u4e00" <= c <= "\u9fff")
            other_count = len(x) - cn_count
            return int(cn_count * 0.65 + other_count / 3.4)
        if isinstance(x, list):
            return sum(walk(i) for i in x)
        if isinstance(x, dict):
            # 识别 Anthropic / OpenAI 格式的 image 块
            if x.get("type") in ("image", "image_url") or "image/" in str(x.get("media_type", "")):
                return 1600
            return sum(walk(v) for v in x.values())
        return 0
    return max(1, walk(obj))


def make_probe_response(parsed):
    return {
        "id": "msg_" + os.urandom(12).hex(),
        "type": "message",
        "role": "assistant",
        "model": map_model(parsed.get("model", "")),
        "content": [{"type": "thinking", "thinking": "ok", "signature": os.urandom(16).hex()}],
        "stop_reason": "max_tokens",
        "stop_sequence": None,
        "usage": {
            "input_tokens": estimate_tokens(parsed),
            "output_tokens": 1,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


def billing_pin_for(parsed):
    """按主/子代理选择计费头固定值，保留 cc_is_subagent 标记供上游/监控区分。"""
    sysv = parsed.get("system")
    if isinstance(sysv, list):
        for b in sysv:
            if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].startswith("x-anthropic-billing-header:"):
                return BILLING_HEADER_PIN_SUBAGENT if "cc_is_subagent=true" in b["text"] else BILLING_HEADER_PIN
    return BILLING_HEADER_PIN


def canonicalize(parsed):
    """Stabilize cache-relevant bytes without touching semantic content."""
    changed = []
    pin = billing_pin_for(parsed)
    sysv = parsed.get("system")
    if isinstance(sysv, list):
        for b in sysv:
            if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].startswith("x-anthropic-billing-header:"):
                if b["text"] != pin:
                    b["text"] = pin
                    changed.append("billing_header")
    for m in parsed.get("messages", []) or []:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            m["content"] = [{"type": "text", "text": c}]
            changed.append("user_content_shape")
    # Pin each session's currentDate to the date of its first request.
    # Claude refreshes the date in msg[0] every day (breaks DeepSeek prefix
    # cache once per day); Codex writes it once at session creation instead.
    current_date = None
    date_like_seen = False
    for m in parsed.get("messages", []) or []:
        if not isinstance(m, dict):
            continue
        for blk in m.get("content") or []:
            if isinstance(blk, dict) and isinstance(blk.get("text"), str):
                mt = DATE_RE.search(blk["text"])
                if mt:
                    current_date = mt.group(1)
                    break
                if not date_like_seen and re.search(r"Today.?s date", blk["text"]):
                    date_like_seen = True
        if current_date:
            break
    if date_like_seen and not current_date:
        # 客户端疑似改了日期行措辞导致 DATE_RE 失效：date_pin 将静默失效，
        # 表现为跨天缓存击穿。记入 changes 使其在 canonicalized 日志中可见。
        changed.append("date_pin_regex_miss")
        log_event({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": "date_pin_regex_miss",
            "hint": "消息中存在疑似日期文本但 DATE_RE 未命中，请核对客户端措辞是否变更",
        })
    date_fixed = fixed_date_for(extract_session_id(parsed), current_date)
    if date_fixed and current_date and date_fixed != current_date:
        pinned = 0
        for m in parsed.get("messages", []) or []:
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if isinstance(c, list):
                for blk in c:
                    if isinstance(blk, dict) and isinstance(blk.get("text"), str):
                        new_text, n = DATE_RE.subn("Today's date is " + date_fixed + ".", blk["text"])
                        if n:
                            blk["text"] = new_text
                            pinned += n
        if pinned:
            changed.append("date_pin")
    return changed, date_fixed


_session_dates = {}
_session_dates_lock = threading.Lock()


def load_session_dates():
    global _session_dates
    try:
        with open(SESSION_DATES_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            _session_dates = data
    except OSError:
        pass


def save_session_dates():
    try:
        tmp = SESSION_DATES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_session_dates, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, SESSION_DATES_FILE)
    except OSError:
        pass


def fixed_date_for(session_id, current_date):
    """Return the pinned date for a session; record it on first sight."""
    if not session_id or not current_date:
        return None
    with _session_dates_lock:
        pinned = _session_dates.get(session_id)
        if pinned is None:
            _session_dates[session_id] = current_date
            save_session_dates()
            return current_date
        return pinned


def classify_kind(parsed):
    sysv = parsed.get("system")
    if isinstance(sysv, list):
        for b in sysv:
            if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].startswith("x-anthropic-billing-header:"):
                return "subagent" if "cc_is_subagent=true" in b["text"] else "main"
    return "main"


def find_session_transcript(session_id):
    if not session_id:
        return None
    matches = glob.glob(os.path.join(PROJECTS_DIR, "*", f"{session_id}.jsonl"))
    return matches[0] if matches else None


def clean_text_for_fp(text):
    if not isinstance(text, str):
        return ""
    # 过滤客户端动态注入的 <system-reminder> 块，确保与转录本底稿精准对齐
    return re.sub(r'<system-reminder>[\s\S]*?</system-reminder>\s*', '', text).strip()


def msg_fingerprint_no_thinking(msg):
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return msg.get("role", "") + ":" + clean_text_for_fp(c)[:200]
    if isinstance(c, list):
        parts = [msg.get("role", "")]
        for b in c:
            if not isinstance(b, dict):
                continue
            btype = b.get("type", "")
            if btype == "thinking":
                continue
            if btype == "text":
                t = clean_text_for_fp(b.get("text", ""))
                if t:
                    parts.append("text:" + t[:200])
            elif btype == "tool_use":
                parts.append("tool_use:" + b.get("id", "") + ":" + b.get("name", ""))
            elif btype == "tool_result":
                t = clean_text_for_fp(str(b.get("content", "")))
                parts.append("tool_result:" + b.get("tool_use_id", "") + ":" + t[:200])
        return "|".join(parts)
    return str(msg)[:200]


def extract_msg_text(msg):
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = [b.get("text", "") for b in c if isinstance(b, dict) and isinstance(b.get("text"), str)]
        return " ".join(out)
    return ""


def parse_transcript_data(tpath):
    msgs = []
    index = {}
    current_asst_blocks = []
    current_turn_thinking = []

    with open(tpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue

            dtype = d.get("type")
            # 遇到压缩分界线 (compact_boundary)，自动清空被压缩丢弃的旧历史消息列表（防止历史越界拼回）
            # 注意：严禁清空 index！thinking 索引是全局查表资产，必须保留全会话各轮次的思维链补齐能力
            if dtype == "system" and d.get("subtype") == "compact_boundary":
                msgs = []
                current_asst_blocks = []
                current_turn_thinking = []
                continue

            msg = d.get("message") or {}
            role = msg.get("role") or ("assistant" if dtype == "assistant" else ("user" if dtype in ("user", "tool_result") else None))

            if dtype in ("user", "tool_result"):
                if current_asst_blocks:
                    msgs.append({"role": "assistant", "content": list(current_asst_blocks)})
                    current_asst_blocks = []
                current_turn_thinking = []
                c = msg.get("content")
                if c:
                    msgs.append({"role": "user", "content": c if isinstance(c, list) else [{"type": "text", "text": str(c)}]})
            elif role == "assistant" or dtype == "assistant":
                c = msg.get("content") or []
                if isinstance(c, list):
                    for b in c:
                        if not isinstance(b, dict):
                            continue
                        current_asst_blocks.append(dict(b))
                        btype = b.get("type")
                        if btype == "thinking":
                            current_turn_thinking.append(b)
                        elif btype == "tool_use" and b.get("id"):
                            if current_turn_thinking:
                                index["tool:" + b["id"]] = list(current_turn_thinking)
                        elif btype == "text" and b.get("text"):
                            if current_turn_thinking:
                                index["text:" + b["text"].strip()[:100]] = list(current_turn_thinking)
                elif isinstance(c, str):
                    current_asst_blocks.append({"type": "text", "text": c})

        if current_asst_blocks:
            msgs.append({"role": "assistant", "content": list(current_asst_blocks)})

    return msgs, index


def hydrate_and_stabilize_messages(parsed, session_id, kind):
    """
    1. 稳定工具顺序 + JSON key 顺序 (Deterministic Tool Sorting + Schema Canonicalization)
    2. 稳定 tool_result 消息顺序 (消除并发工具调用返回乱序)
    3. 智能拼接微折叠的历史消息 (Tool History Folding)
    4. 智能回填被客户端剥离的 thinking blocks (Thinking Hydration)
    注：压缩边界已在 parse_transcript_data 中由 compact_boundary 物理截断，无需任何关键词匹配！
    """
    changed = []

    # 1. 稳定工具列表顺序 + JSON key 顺序 (消除异步握手乱序 + 序列化不确定性)
    tools = parsed.get("tools")
    if isinstance(tools, list):
        tools.sort(key=lambda t: t.get("name", "") if isinstance(t, dict) else "")
        # 对 input_schema 做 sort_keys 重新序列化，确保 JSON key 顺序确定
        for t in tools:
            if isinstance(t, dict) and "input_schema" in t:
                schema = t["input_schema"]
                if isinstance(schema, dict):
                    t["input_schema"] = json.loads(json.dumps(schema, sort_keys=True))

    # 2. 稳定 tool_result 顺序 (消除并发工具调用返回乱序导致的前缀变化)
    #    Claude Code 使用 Anthropic 协议：并发工具返回位于单条 role: "user" 消息内的 content 块数组中，按 tool_use_id 排序
    incoming_msgs = parsed.get("messages")
    if isinstance(incoming_msgs, list):
        for m in incoming_msgs:
            if isinstance(m, dict) and m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, list) and len(content) > 1:
                    has_tool_results = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                    if has_tool_results:
                        orig_ids = [b.get("tool_use_id", "") for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                        # 稳定排序：保持非 tool_result 块在前，tool_result 块严格按 tool_use_id 排序
                        content.sort(key=lambda b: (0 if (isinstance(b, dict) and b.get("type") != "tool_result") else 1, b.get("tool_use_id", "") if isinstance(b, dict) else ""))
                        new_ids = [b.get("tool_use_id", "") for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                        if orig_ids != new_ids:
                            changed.append("tool_result_blocks_sorted_%d" % len(orig_ids))

    if not session_id or not isinstance(incoming_msgs, list) or not incoming_msgs:
        return changed

    # 3. 检查是否有 missing thinking
    missing_thinking = False
    for m in incoming_msgs:
        if isinstance(m, dict) and m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, str):
                missing_thinking = True
                break
            if isinstance(c, list):
                if not any(isinstance(b, dict) and b.get("type") == "thinking" for b in c):
                    missing_thinking = True
                    break

    transcript_msgs = None
    thinking_index = None

    # 统一读取 transcript（只调一次 glob + parse）
    tpath = find_session_transcript(session_id)
    if tpath:
        transcript_msgs, thinking_index = parse_transcript_data(tpath)

    if not transcript_msgs:
        return changed

    # 未缺失 thinking 时，快速判断是否发生消息折叠（首条消息被截断）
    if not missing_thinking:
        if len(incoming_msgs) < len(transcript_msgs):
            first_fp = msg_fingerprint_no_thinking(incoming_msgs[0])
            if msg_fingerprint_no_thinking(transcript_msgs[0]) == first_fp:
                return changed  # 0ms 快路径！
        else:
            return changed  # 0ms 快路径！

    # 4. 消息折叠恢复 (Un-folding)
    first_fp = msg_fingerprint_no_thinking(incoming_msgs[0])
    match_idx = -1
    if len(incoming_msgs) < len(transcript_msgs):
        for idx, cm in enumerate(transcript_msgs):
            if msg_fingerprint_no_thinking(cm) == first_fp:
                match_idx = idx
                break
        if match_idx > 0:
            missing_prefix = [dict(m) for m in transcript_msgs[:match_idx]]
            incoming_msgs = missing_prefix + incoming_msgs
            parsed["messages"] = incoming_msgs
            changed.append(f"hydrate_folded_{len(missing_prefix)}_msgs")

    # 5. Thinking 智能补齐
    restored_count = 0
    for m in incoming_msgs:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, str):
            c = [{"type": "text", "text": c}]
            m["content"] = c
        if not isinstance(c, list):
            continue
        has_thinking = any(isinstance(b, dict) and b.get("type") == "thinking" for b in c)
        if has_thinking:
            continue
        thinking_to_inject = None
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("id"):
                key = "tool:" + b["id"]
                if key in thinking_index:
                    thinking_to_inject = thinking_index[key]
                    break
            elif b.get("type") == "text" and b.get("text"):
                key = "text:" + b["text"].strip()[:100]
                if key in thinking_index:
                    thinking_to_inject = thinking_index[key]
                    break
        if thinking_to_inject:
            m["content"] = thinking_to_inject + [
                b for b in c if not (isinstance(b, dict) and b.get("type") == "thinking")
            ]
            restored_count += 1

    if restored_count:
        changed.append(f"hydrate_thinking_{restored_count}")

    return changed


def extract_usage(data):
    if isinstance(data, (bytes, bytearray)):
        text = bytes(data).decode("utf-8", "replace")
    else:
        text = data or ""
    if text.lstrip().startswith("{"):
        try:
            return json.loads(text).get("usage")
        except Exception:
            pass
    usage = {}
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                d = json.loads(line[6:])
            except Exception:
                continue
            if d.get("type") == "message_start":
                m = d.get("message", {})
                if m.get("usage") and isinstance(m["usage"], dict):
                    usage.update(m["usage"])
            if d.get("type") == "message_delta":
                if d.get("usage") and isinstance(d["usage"], dict):
                    usage.update(d["usage"])
    return usage if usage else None


class UsageCapture:
    """流式 usage 提取器：只保留 message_start 和尾部滑动窗口，不缓存全量响应体。"""
    WINDOW_SIZE = 8192  # 尾部滑动窗口大小（字节）

    def __init__(self):
        self._usage = {}
        self._tail = b""
        self._tail_len = 0

    def feed(self, chunk: bytes):
        """喂入一块原始字节流，增量提取 usage。"""
        # 逐行扫描 message_start（出现在流的最前面）
        if not self._usage:
            text = chunk.decode("utf-8", "replace")
            for line in text.splitlines():
                if line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                    except Exception:
                        continue
                    if d.get("type") == "message_start":
                        m = d.get("message", {})
                        if m.get("usage") and isinstance(m["usage"], dict):
                            self._usage.update(m["usage"])
        # 尾部滑动窗口：只保留最后 WINDOW_SIZE 字节（用于提取 message_delta）
        self._tail += chunk
        self._tail_len += len(chunk)
        if self._tail_len > self.WINDOW_SIZE * 2:
            self._tail = self._tail[-self.WINDOW_SIZE:]
            self._tail_len = len(self._tail)

    def get_usage(self):
        """从尾部窗口中提取 message_delta 的 usage，与 message_start 合并返回。"""
        usage = dict(self._usage)
        text = self._tail.decode("utf-8", "replace")
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                except Exception:
                    continue
                if d.get("type") == "message_delta":
                    if d.get("usage") and isinstance(d["usage"], dict):
                        usage.update(d["usage"])
        return usage if usage else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        if self.path.split("?")[0] == "/v1/models":
            self._send_json(200, {
                "object": "list",
                "data": [{"id": m, "object": "model"} for m in MODEL_LIST],
            })
            log_event({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "method": "GET",
                "path": self.path,
                "client": self.client_address[0],
                "ua": self.headers.get("User-Agent", ""),
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        started = time.time()
        if self.path.split("?")[0] != "/v1/messages":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            log_event({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "method": "POST",
                "path": self.path,
                "client": self.client_address[0],
                "event": "invalid_json",
            })
            self._send_json(400, {
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "invalid JSON body"},
            })
            return

        original = parsed.get("model", "")
        bump_stats(requests=1)
        session_id = extract_session_id(parsed)
        touch_active_session(session_id)
        x_opencode_session = "claude-" + (session_id or "unknown")
        mapped = map_model(original)
        kind = classify_kind(parsed)
        changes = []
        log_event({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "method": "POST",
            "path": self.path,
            "client": self.client_address[0],
            "model_requested": original,
            "model_mapped": map_model(original),
            "session_id": session_id,
            "x_opencode_session": x_opencode_session,
            "messages": len(parsed.get("messages", []) or []),
            "max_tokens": parsed.get("max_tokens"),
            "stream": parsed.get("stream"),
            "tools": len(parsed.get("tools", []) or []),
            "kind": kind,
            "ua": self.headers.get("User-Agent", ""),
        })
        if CACHE_STABILIZE and is_probe_request(parsed):
            resp = make_probe_response(parsed)
            log_event({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "method": "POST",
                "path": self.path,
                "client": self.client_address[0],
                "model_requested": original,
                "model_mapped": mapped,
                "event": "probe_local",
                "estimated_input_tokens": resp["usage"]["input_tokens"],
            })
            bump_stats(probe_local=1)
            record_session(session_id, "probe_local", kind=kind)
            self._send_json(200, resp)
            return
        if CACHE_STABILIZE:
            hydrate_changed = hydrate_and_stabilize_messages(parsed, session_id, kind)
            changed, date_fixed = canonicalize(parsed)
            changed = hydrate_changed + changed
            changes[:] = changed
            for c in changed:
                if c == "billing_header":
                    bump_stats(billing_pin=1)
                elif c == "date_pin":
                    bump_stats(date_pin=1)
                elif c == "user_content_shape":
                    bump_stats(user_content_shape=1)
            if changed:
                log_event({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "method": "POST",
                    "path": self.path,
                    "client": self.client_address[0],
                    "model_mapped": mapped,
                    "event": "canonicalized",
                    "changes": changed,
                    "date_fixed": date_fixed or "",
                })
        parsed["model"] = mapped
        upstream_url = normalize_upstream(os.environ.get("UPSTREAM_URL") or load_upstream())
        if not upstream_url:
            self._send_json(503, {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "ccds-bridge: 未配置上游（upstream_url）。请在 3P 设置里填写要访问的真实地址，保存后插件会自动接管。",
                },
            })
            return
        payload = json.dumps(parsed).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": client_api_key(self.headers),
            "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
            "Accept": self.headers.get("Accept", "application/json"),
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(upstream_url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as upstream:
                self.send_response(upstream.status)
                self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.close_connection = True
                rid = upstream.headers.get("request-id")
                if rid:
                    self.send_header("request-id", rid)
                self.end_headers()
                cap = UsageCapture()
                disconnected = False
                while True:
                    chunk = upstream.read(4096)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        disconnected = True
                        break
                    cap.feed(chunk)
                elapsed_ms = int((time.time() - started) * 1000)
                if disconnected:
                    log_event({
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "method": "POST",
                        "client": self.client_address[0],
                        "model_mapped": parsed["model"],
                        "event": "client_disconnected",
                        "elapsed_ms": elapsed_ms,
                    })
                    return
                usage = cap.get_usage()
                bump_stats(
                    upstream_ok=1,
                    input_tokens=(usage or {}).get("input_tokens") or 0,
                    cache_read=(usage or {}).get("cache_read_input_tokens") or 0,
                    output_tokens=(usage or {}).get("output_tokens") or 0,
                )
                record_session(
                    session_id,
                    "upstream_ok",
                    messages=len(parsed.get("messages", []) or []),
                    usage=usage,
                    kind=kind,
                )
                log_event({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "method": "POST",
                    "client": self.client_address[0],
                    "model_mapped": parsed["model"],
                    "event": "upstream_ok",
                    "status": upstream.status,
                    "elapsed_ms": elapsed_ms,
                    "request_id": upstream.headers.get("request-id", ""),
                })
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            bump_stats(http_errors=1)
            log_event({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "method": "POST",
                "client": self.client_address[0],
                "model_mapped": parsed["model"],
                "event": "upstream_http_error",
                "status": exc.code,
                "elapsed_ms": int((time.time() - started) * 1000),
            })
            self.send_response(exc.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            try:
                self.wfile.write(detail.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        except Exception as exc:
            bump_stats(http_errors=1)
            log_event({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "method": "POST",
                "client": self.client_address[0],
                "model_mapped": parsed["model"],
                "event": "upstream_error",
                "error": str(exc),
                "elapsed_ms": int((time.time() - started) * 1000),
            })
            try:
                self._send_json(502, {
                    "type": "error",
                    "error": {"type": "api_error", "message": str(exc)},
                })
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == "__main__":
    import socket as _socket

    def _find_free_port(preferred, limit):
        for port in range(preferred, preferred + limit):
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _load_saved_port():
        try:
            cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
            p = cfg.get("gateway_port")
            if isinstance(p, int) and p > 0:
                return p
        except Exception:
            pass
        return None

    def _save_port_to_config(port):
        """把最终确定的端口写回 config.json（原子写），同时更新 3P 配置文件地址。"""
        try:
            try:
                cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
            except Exception:
                cfg = {}
            old_port = cfg.get("gateway_port")
            cfg["gateway_port"] = port
            os.makedirs(BASE_DIR, exist_ok=True)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, CONFIG_FILE)
            # 若端口发生变化，同步更新 3P 配置文件中的地址
            if old_port and old_port != port:
                _update_3p_gateway_url(port)
        except OSError:
            pass

    def _update_3p_gateway_url(new_port):
        """将 Claude 3P configLibrary 里的本地网关地址更新为新端口。"""
        try:
            if os.name == "nt":
                import os as _os
                pat = _os.path.expandvars(r"%APPDATA%\Claude-3p\configLibrary\*.json")
            else:
                pat = os.path.expanduser(
                    "~/Library/Application Support/Claude-3p/configLibrary/*.json"
                )
            import glob as _glob
            new_url = "http://127.0.0.1:%d" % new_port
            for path in _glob.glob(pat):
                try:
                    data = json.load(open(path, encoding="utf-8"))
                    cur = (data.get("inferenceGatewayBaseUrl") or "").strip().rstrip("/")
                    if cur.startswith("http://127.0.0.1:") and cur != new_url:
                        data["inferenceGatewayBaseUrl"] = new_url
                        tmp = path + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as fh:
                            json.dump(data, fh, ensure_ascii=False, indent=2)
                        os.replace(tmp, path)
                        print("updated 3P gateway URL: %s -> %s" % (cur, new_url), flush=True)
                except Exception:
                    pass
        except Exception:
            pass

    cleanup_runtime()
    load_session_dates()
    load_session_stats()

    # 确定要监听的端口（优先 config 记录值，次选首选值，最后自动扫描）
    saved = _load_saved_port()
    candidate = saved if saved else PORT_PREFERRED
    PORT = _find_free_port(candidate, PORT_SCAN_LIMIT)
    if PORT != candidate:
        print(
            "gateway: 端口 %d 被占用，自动切换至 %d" % (candidate, PORT),
            flush=True,
        )

    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print("gateway 启动失败（端口 %d 不可用）: %s" % (PORT, exc), flush=True)
        raise SystemExit(1)

    # 启动成功后把实际使用的端口持久化（manager 和 keepalive 依赖此值）
    _save_port_to_config(PORT)

    print("claude-gateway listening on http://%s:%d" % (HOST, PORT), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
