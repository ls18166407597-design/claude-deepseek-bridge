#!/usr/bin/env python3
"""ccds-bridge 本地进程管理器：gateway（中转）+ keepalive（保活）。"""
import json
import glob
import os
import errno
import signal
import socket
import subprocess
import sys
import time
import urllib.request

BASE = os.environ.get("CCDS_BRIDGE_HOME", os.path.expanduser("~/.ccds-bridge"))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GATEWAY = os.path.join(SCRIPT_DIR, "gateway.py")
KEEPALIVE = os.path.join(SCRIPT_DIR, "keepalive.py")
GATEWAY_PID = os.path.join(BASE, "gateway.pid")
KEEPALIVE_PID = os.path.join(BASE, "keepalive.pid")
CONFIG = os.path.join(BASE, "config.json")
PORT_PREFERRED = int(os.environ.get("GATEWAY_PORT", "8789"))
PORT_SCAN_LIMIT = 20   # 最多向上扫描 20 个端口（8789~8808）
THREEP_CONFIG_GLOB = os.environ.get(
    "CCDS_3P_CONFIG_GLOB",
    (os.path.expandvars(r"%APPDATA%\Claude-3p\configLibrary\*.json")
     if os.name == "nt"
     else os.path.expanduser("~/Library/Application Support/Claude-3p/configLibrary/*.json")),
)


def find_free_port(preferred=PORT_PREFERRED, limit=PORT_SCAN_LIMIT):
    """从 preferred 开始向上扫描，返回第一个可绑定的端口号。"""
    for port in range(preferred, preferred + limit):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    # 兜底：让 OS 分配一个随机端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load_port():
    """从 config.json 读取上次选定的端口；不存在则返回 None。"""
    try:
        cfg = json.load(open(CONFIG, encoding="utf-8"))
        p = cfg.get("gateway_port")
        if isinstance(p, int) and p > 0:
            return p
    except Exception:
        pass
    return None


def save_port(port, cfg=None):
    """把端口号写入 config.json（与其他字段合并，原子写）。"""
    try:
        if cfg is None:
            try:
                cfg = json.load(open(CONFIG, encoding="utf-8"))
            except Exception:
                cfg = {}
        cfg["gateway_port"] = port
        os.makedirs(BASE, exist_ok=True)
        tmp = CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, CONFIG)
    except OSError:
        pass


def effective_port():
    """返回当前网关实际使用的端口（优先 config 已记录值，否则重新扫描）。"""
    return load_port() or PORT_PREFERRED


def local_gateway_url(port=None):
    return "http://127.0.0.1:%d" % (port or effective_port())


def ensure_dirs():
    os.makedirs(BASE, exist_ok=True)
    os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)


def acquire_lock():
    """跨进程互斥：多个会话同时 SessionStart 时，sync/spawn 串行执行。"""
    lock_path = os.path.join(BASE, "spawn.lock")
    for _ in range(300):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            try:
                stale = int(open(lock_path, encoding="utf-8").read().strip())
                os.kill(stale, 0)
            except Exception:
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
            time.sleep(0.01)
    print("警告：等待 spawn 锁超时，继续执行")
    return None


def release_lock(fd):
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(os.path.join(BASE, "spawn.lock"))
    except OSError:
        pass


def is_running(pid_file):
    try:
        pid = int(open(pid_file, encoding="utf-8").read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def gateway_alive():
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % effective_port(), timeout=2)
        return True
    except Exception:
        return False


def check_runtime_dir():
    """插件更新后代码路径变化：下次开会话自动重启本地服务，让新代码生效。
    应用退出/重启不会杀掉这些独立常驻进程，靠路径对比来判断是否需要换新代码。"""
    ensure_dirs()
    lock = acquire_lock()
    try:
        cfg = {}
        if os.path.exists(CONFIG):
            try:
                cfg = json.load(open(CONFIG, encoding="utf-8"))
            except Exception:
                cfg = {}
        old = cfg.get("runtime_script_dir")
        if old and old != SCRIPT_DIR:
            qprint("插件代码路径变化：%s -> %s，重启本地服务" % (old, SCRIPT_DIR))
            stop(KEEPALIVE_PID, "keepalive")
            stop(GATEWAY_PID, "gateway")
        cfg["runtime_script_dir"] = SCRIPT_DIR
        with open(CONFIG, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=1)
    finally:
        release_lock(lock)


def find_3p_configs():
    """桌面版 3P 配置文件：包含 inferenceGatewayBaseUrl 的 configLibrary JSON。"""
    found = []
    for path in glob.glob(THREEP_CONFIG_GLOB):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("inferenceGatewayBaseUrl"):
            found.append((path, data))
    return found


def normalize_upstream(url):
    """3P 填的是 base URL（应用会自动拼 /v1/messages），本地网关转发时需要完整端点。"""
    url = (url or "").strip().rstrip("/")
    if url and not url.endswith("/v1/messages"):
        url += "/v1/messages"
    return url


def sync():
    """3P 填真实供应商地址，插件自动改写成本地网关并记住上游。
    只在 3P 配置文件变更（mtime 更新）时才处理，其余会话直接跳过。"""
    ensure_dirs()
    lock = acquire_lock()
    try:
        return _sync_locked()
    finally:
        release_lock(lock)


def _sync_locked():
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            cfg = json.load(open(CONFIG, encoding="utf-8"))
        except Exception:
            cfg = {}
    last_sync = cfg.get("last_sync_ts") or 0
    newest = 0.0
    for path in glob.glob(THREEP_CONFIG_GLOB):
        try:
            newest = max(newest, os.path.getmtime(path))
        except OSError:
            pass
    if last_sync and newest <= last_sync:
        upstream = cfg.get("upstream_url")
        if upstream:
            qprint("配置无变化，跳过 sync（upstream:", upstream, "）")
            return upstream
        qprint("配置无变化但 upstream 缺失，进入恢复逻辑")
    changed = []

    # 在 sync 阶段确定本次要用的端口：
    # 如果网关已在运行（port 已记录），沿用原端口；否则扫描空闲端口并持久化。
    port = load_port()
    if port and gateway_alive():
        # 网关已运行，沿用
        pass
    else:
        port = find_free_port()
        save_port(port, cfg)
        cfg["gateway_port"] = port  # 同步更新内存中的 cfg
    cur_local_url = "http://127.0.0.1:%d" % port

    # 桌面版 3P 配置
    for path, data in find_3p_configs():
        url = (data.get("inferenceGatewayBaseUrl") or "").strip().rstrip("/")
        if not url:
            continue
        if url != cur_local_url:
            cfg["upstream_url"] = normalize_upstream(url)
            try:
                backup = path + ".bak-ccds"
                with open(backup, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                os.chmod(backup, 0o600)
                data["inferenceGatewayBaseUrl"] = cur_local_url
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                changed.append("3P: %s -> %s (upstream %s)" % (url, cur_local_url, cfg["upstream_url"]))
            except OSError as exc:
                print("3P 配置改写失败:", path, exc)
    # 兜底：并发旧版本曾导致 upstream 丢失（3P 已是本地地址但 config 无上游），从备份恢复
    if not cfg.get("upstream_url"):
        for path, data in find_3p_configs():
            url = (data.get("inferenceGatewayBaseUrl") or "").strip().rstrip("/")
            # 匹配任何 127.0.0.1 本地地址（端口可能因重选而变化）
            if url.startswith("http://127.0.0.1:"):
                try:
                    with open(path + ".bak-ccds", encoding="utf-8") as fh:
                        bak = json.load(fh)
                    bak_url = (bak.get("inferenceGatewayBaseUrl") or "").strip().rstrip("/")
                    if bak_url and not bak_url.startswith("http://127.0.0.1:"):
                        cfg["upstream_url"] = normalize_upstream(bak_url)
                        qprint("recovered upstream from backup:", cfg["upstream_url"])
                except OSError:
                    pass
    cfg["last_sync_ts"] = time.time()
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=1)
    for line in changed:
        qprint("synced:", line)
    if changed and gateway_alive():
        stop(GATEWAY_PID, "gateway")
        if _spawn_unlocked(GATEWAY, [], "gateway", GATEWAY_PID):
            qprint("gateway 已重启以应用新上游")
    upstream = cfg.get("upstream_url")
    if not upstream:
        print("未配置上游：请在 3P 设置里把网关地址填成你要访问的真实地址"
              "（保存后应用会重启），插件下次会自动接管。")
        return None
    qprint("upstream_url:", upstream)
    return upstream


def _spawn_unlocked(script, args, name, pid_file):
    if is_running(pid_file) or (name == "gateway" and gateway_alive()):
        qprint("%s already running" % name)
        return False
    log = open(os.path.join(BASE, "logs", name + ".log"), "a", encoding="utf-8")
    kwargs = {"stdout": log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, script] + args,
        **kwargs
    )
    with open(pid_file, "w", encoding="utf-8") as fh:
        fh.write(str(proc.pid))
    qprint("%s started (pid %d)" % (name, proc.pid))
    return True


def spawn(script, args, name, pid_file):
    ensure_dirs()
    lock = acquire_lock()
    try:
        _spawn_unlocked(script, args, name, pid_file)
    finally:
        release_lock(lock)


def stop(pid_file, name):
    if not is_running(pid_file):
        qprint("%s not running" % name)
        return
    try:
        pid = int(open(pid_file, encoding="utf-8").read().strip())
        sig_term = getattr(signal, "SIGTERM", signal.SIGINT)
        sig_kill = getattr(signal, "SIGKILL", sig_term)
        os.kill(pid, sig_term)
        # 等进程真正退出再删 pid 文件
        for _ in range(30):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, OSError):
                break
        else:
            os.kill(pid, sig_kill)
            time.sleep(0.2)
    except Exception as exc:
        print("stop %s error: %s" % (name, exc))
    try:
        os.remove(pid_file)
    except OSError:
        pass
    qprint("%s stopped" % name)


def start():
    check_runtime_dir()
    spawn(GATEWAY, [], "gateway", GATEWAY_PID)
    spawn(KEEPALIVE, ["--daemon"], "keepalive", KEEPALIVE_PID)


def stop_all():
    stop(KEEPALIVE_PID, "keepalive")
    stop(GATEWAY_PID, "gateway")


def status():
    gw = gateway_alive()
    ka = is_running(KEEPALIVE_PID)
    print("gateway:   %s (http://127.0.0.1:%d)" % ("running" if gw else "stopped", effective_port()))
    print("keepalive: %s" % ("running" if ka else "stopped"))
    stats_file = os.path.join(BASE, "stats.json")
    if os.path.exists(stats_file):
        try:
            s = json.load(open(stats_file, encoding="utf-8"))
            total = s.get("input_tokens", 0) + s.get("cache_read", 0)
            hit = s.get("cache_read", 0) / total * 100 if total else 0
            print("requests:   %d (upstream %d, probe intercepted %d)"
                  % (s.get("requests", 0), s.get("upstream_ok", 0), s.get("probe_local", 0)))
            print("fixes:      billing_pin %d, date_pin %d, shape %d"
                  % (s.get("billing_pin", 0), s.get("date_pin", 0), s.get("user_content_shape", 0)))
            print("cache:      %d read / %d total = %.1f%% hit"
                  % (s.get("cache_read", 0), total, hit))
            print("errors:     %d" % s.get("http_errors", 0))
        except Exception as exc:
            print("stats read error: %s" % exc)


QUIET = False


def qprint(*args, **kwargs):
    """静默模式下不输出（除非是错误场景，错误场景请直接用 print）。"""
    if not QUIET:
        print(*args, **kwargs)


def main():
    global QUIET
    args = [a for a in sys.argv[1:] if a != "--quiet"]
    QUIET = "--quiet" in sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "start":
        start()
    elif cmd == "stop":
        stop_all()
    elif cmd == "restart":
        stop_all()
        start()
    elif cmd == "ensure":
        check_runtime_dir()
        sync()
        if not gateway_alive():
            spawn(GATEWAY, [], "gateway", GATEWAY_PID)
        if not is_running(KEEPALIVE_PID):
            spawn(KEEPALIVE, ["--daemon"], "keepalive", KEEPALIVE_PID)
    elif cmd == "sync":
        sync()
    else:
        status()


if __name__ == "__main__":
    main()
