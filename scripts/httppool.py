#!/usr/bin/env python3
"""轻量 HTTPS 连接池（仅标准库）：复用上游连接，消除每请求 TLS 握手开销。

设计要点：
- 池按 (host, port) 分桶；取连接时不做活性探测，陈旧连接由
  request_with_retry 的「连接期安全重试」兜底。
- 流式响应：调用方读完响应体后必须调用 release(key, conn, reusable)；
  客户端中断或响应未读完时 reusable=False，连接直接关闭不复用。
- 重试边界从严：仅当请求确定未被上游处理时才重试（发送阶段失败、
  空状态行 BadStatusLine）；getresponse 超时等模糊失败不重试，
  避免 LLM 调用被重复计费。
"""
import http.client
import ssl
import threading
from urllib.parse import urlsplit

DEFAULT_TIMEOUT = 300


class ConnPool:
    def __init__(self, max_idle_per_host=8, timeout=DEFAULT_TIMEOUT):
        self._max_idle = max_idle_per_host
        self._timeout = timeout
        self._idle = {}
        self._lock = threading.Lock()

    def _new_conn(self, key):
        host, port = key
        return http.client.HTTPSConnection(
            host, port, timeout=self._timeout,
            context=ssl.create_default_context(),
        )

    def acquire(self, key):
        with self._lock:
            lst = self._idle.get(key)
            if lst:
                return lst.pop()
        return self._new_conn(key)

    def release(self, key, conn, reusable):
        if not reusable:
            self._close(conn)
            return
        with self._lock:
            lst = self._idle.setdefault(key, [])
            if len(lst) < self._max_idle:
                lst.append(conn)
                return
        self._close(conn)

    @staticmethod
    def _close(conn):
        try:
            conn.close()
        except Exception:
            pass


_POOLS = {}
_POOLS_LOCK = threading.Lock()


def pool_for(url_or_netloc, timeout=DEFAULT_TIMEOUT):
    """按 netloc 取池；入参兼容完整 URL（内部自动提取），避免调用方误建空池。"""
    netloc = url_or_netloc
    if "://" in url_or_netloc:
        netloc = urlsplit(url_or_netloc).netloc
    with _POOLS_LOCK:
        pool = _POOLS.get((netloc, timeout))
        if pool is None:
            pool = ConnPool(timeout=timeout)
            _POOLS[(netloc, timeout)] = pool
        return pool


def request_with_retry(method, url, body, headers, timeout=DEFAULT_TIMEOUT, retries=1):
    """发起 HTTPS 请求，返回 (key, conn, response)。

    调用方消费完响应后负责 POOL.release(key, conn, reusable)。
    仅在「请求未被上游处理」的失败场景重试（见模块 docstring）。
    """
    parts = urlsplit(url)
    key = (parts.hostname, parts.port or 443)
    path = parts.path + (("?" + parts.query) if parts.query else "")
    pool = pool_for(parts.netloc, timeout)
    last_exc = None
    for _ in range(retries + 1):
        conn = pool.acquire(key)
        try:
            conn.request(method, path, body=body, headers=headers)
        except Exception as exc:
            pool.release(key, conn, False)
            last_exc = exc
            continue
        try:
            resp = conn.getresponse()
            return key, conn, resp
        except http.client.BadStatusLine:
            # 空状态行 = 连接在空闲期被对端关闭，请求未被处理，可安全重试
            pool.release(key, conn, False)
            last_exc = http.client.BadStatusLine("")
            continue
        except Exception:
            # 模糊失败（如读响应头超时）：上游可能已处理，不重试
            pool.release(key, conn, False)
            raise
    raise last_exc
