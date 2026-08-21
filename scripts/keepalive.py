#!/usr/bin/env python3
"""ccds-bridge 网关看门狗守护脚本。

每 60 秒探活 8789 端口，若网关进程意外退出则自动拉起。
注：因 v0.1.23 已上线网关层 Hydration（前缀重塑与思维链回填），
本脚本不再修改或触碰任何本地 transcript 会话文件。
"""
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE_DIR = os.environ.get("CCDS_BRIDGE_HOME", os.path.expanduser("~/.ccds-bridge"))
LOG = os.path.join(BASE_DIR, "logs", "keepalive.log")
MAX_LOG_BYTES = 64 * 1024  # 日志超过 64KB 时轮转
MAX_LOG_LINES = 50
_GATEWAY_PORT_DEFAULT = int(os.environ.get("GATEWAY_PORT", "8789"))
GATEWAY_CHECK_INTERVAL = 60  # 看门狗探活间隔（秒）


def load_gateway_port():
    """从 config.json 读取网关实际使用的端口，读取失败则用默认值。"""
    try:
        cfg = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
        p = cfg.get("gateway_port")
        if isinstance(p, int) and p > 0:
            return p
    except Exception:
        pass
    return _GATEWAY_PORT_DEFAULT


def append_log(line):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_LOG_BYTES:
            lines = open(LOG, encoding="utf-8").read().splitlines()
            with open(LOG, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines[-MAX_LOG_LINES:]) + "\n")
    except OSError:
        pass
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

def gateway_alive():
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % load_gateway_port(), timeout=2)
        return True
    except Exception:
        return False


def ensure_gateway():
    """看门狗：网关进程意外退出后 60 秒内自动拉起。"""
    if gateway_alive():
        return False
    pid_file = os.path.join(BASE_DIR, "gateway.pid")
    try:
        pid = int(open(pid_file, encoding="utf-8").read().strip())
        os.kill(pid, 0)
        return False
    except Exception:
        pass
    script = None
    try:
        cfg = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
        candidate = os.path.join(cfg.get("runtime_script_dir") or "", "gateway.py")
        if os.path.isfile(candidate):
            script = candidate
    except Exception:
        pass
    if not script:
        append_log("watchdog: gateway down but runtime_script_dir not found in config.json; skip")
        return False
    try:
        with open(os.path.join(BASE_DIR, "logs", "gateway.log"), "a", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, script],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        with open(pid_file, "w", encoding="utf-8") as fh:
            fh.write(str(proc.pid))
        append_log("watchdog: gateway down, respawned (pid %d)" % proc.pid)
        return True
    except Exception as exc:
        append_log("watchdog: gateway respawn failed: %s" % exc)
        return False


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        while True:
            try:
                ensure_gateway()
            except Exception as exc:
                append_log("watchdog error: %s" % exc)
            time.sleep(GATEWAY_CHECK_INTERVAL)
    else:
        port = load_gateway_port()
        status = "alive" if gateway_alive() else "down"
        print("gateway port %d is %s" % (port, status))
