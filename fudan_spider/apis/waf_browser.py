"""
在无头 Chrome 页面里代发 booking.fudan.edu.cn 的 POST 请求。

瑞数 WAF 对 POST 额外要求一个动态 URL 后缀（形如 ?pmE3tlaC=...），由页面里的
质询 JS 劫持 XHR 时现场生成，纯 HTTP 客户端无法构造，直接 POST 一律 412。
GET 不需要后缀，所以查询仍走 curl_cffi，只有写操作（预约 / 取消）经过这里。

用法:
    from fudan_spider.apis.waf_browser import waf_post
    body = waf_post(se, "/reservation/site/resource/launch", {"data": ..., ...})

浏览器按 Session 复用：同一个 se 的多次 POST 共用一个页面（抢场时只付一次启动开销），
换了 se（重新登录）就关掉旧浏览器、用新 cookie 重开。所有 Playwright 调用都在
一个专用线程里执行，因此在 asyncio 事件循环（FastMCP 工具）里调用也安全。
"""

import atexit
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

BOOKING_HOST = "booking.fudan.edu.cn"
_PAGE = f"https://{BOOKING_HOST}/reservation/fe/site/special/special?id=48"
_AUTH_PROBE = "/reservation/site/appointment/appointment-list?p=1&pageSize=1&type=0"
_WAF_COOKIE_NAMES = {"7GdWaAWutylUO", "7GdWaAWutylUP", "0a2b5cfd50f6f39396"}

_XHR_POST = """([path, fields, timeoutMs]) => new Promise(resolve => {
    const fd = new FormData();
    for (const k in fields) fd.append(k, fields[k]);
    const x = new XMLHttpRequest();
    x.open('POST', path);
    x.timeout = timeoutMs;
    x.onload = () => resolve([x.status, x.responseText]);
    x.onerror = () => resolve([0, 'network error']);
    x.ontimeout = () => resolve([0, 'timeout']);
    x.send(fd);
})"""


class _Browser:
    """单个无头 Chrome + 停在 booking 前端页的标签页。只能在 _executor 线程里使用。"""

    def __init__(self, cookies: list[dict], user_agent: str, timeout: float):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                headless=True, channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
            # 瑞数会识别 HeadlessChrome UA 和 navigator.webdriver，两者都要处理；
            # 预约站的登录会话又绑定 UA，所以直接沿用 Session 登录时的 UA
            ctx = self._browser.new_context(user_agent=user_agent)
            ctx.add_cookies(cookies)
            self.page = ctx.new_page()
            self.page.goto(_PAGE, wait_until="domcontentloaded", timeout=timeout * 1000)
            # 会话 cookie 不全时页面会经 id.fudan.edu.cn 单点登录再跳回来
            deadline = time.time() + timeout
            while not self.page.url.startswith(f"https://{BOOKING_HOST}/reservation/fe/"):
                if time.time() > deadline:
                    raise RuntimeError(f"前端页未就绪，停在 {self.page.url[:80]}")
                time.sleep(0.25)
            self.page.wait_for_load_state("domcontentloaded")
            status, text = self.page.evaluate(
                "(p) => fetch(p).then(async r => [r.status, await r.text()])", _AUTH_PROBE
            )
            if status != 200 or '"e":"OK"' not in text:
                raise RuntimeError(f"浏览器内未登录（{status}）: {text[:80]}")
        except Exception:
            self.close()
            raise

    def post(self, path: str, fields: dict, timeout: float) -> tuple[int, str]:
        return self.page.evaluate(_XHR_POST, [path, fields, int(timeout * 1000)])

    def close(self) -> None:
        for fn in (getattr(self, "_browser", None) and self._browser.close, self._pw.stop):
            try:
                if fn:
                    fn()
            except Exception:
                pass


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="waf-browser")
_lock = threading.Lock()
_current: tuple[int, _Browser] | None = None   # (id(se), browser)


def _session_cookies(se) -> list[dict]:
    """取出 Session 里除 WAF 质询 cookie 以外的全部 cookie（浏览器会自己解质询）。"""
    out = []
    for c in se.cookies.jar:
        if c.name in _WAF_COOKIE_NAMES:
            continue
        out.append({
            "name": c.name, "value": c.value,
            "domain": c.domain, "path": c.path or "/",
            "secure": bool(c.secure),
        })
    return out


def _ensure(se, timeout: float) -> _Browser:
    """在 _executor 线程里调用：返回绑定到 se 的浏览器，必要时（重新）启动。"""
    global _current
    if _current is not None and _current[0] == id(se):
        return _current[1]
    if _current is not None:
        _current[1].close()
        _current = None
    t = time.time()
    browser = _Browser(_session_cookies(se), se.headers["User-Agent"], timeout)
    log.info("WAF 浏览器就绪（%.1fs）", time.time() - t)
    _current = (id(se), browser)
    return browser


def _close_current() -> None:
    global _current
    if _current is not None:
        _current[1].close()
        _current = None


def prepare(se, timeout: float = 40.0) -> None:
    """预热：提前为 se 启动浏览器，让之后的 waf_post 不再付启动开销（抢场前调用）。"""
    with _lock:
        _executor.submit(_ensure, se, timeout).result()


def waf_post(se, path: str, fields: dict, timeout: float = 40.0) -> dict:
    """
    以 se 的登录身份，从浏览器页面内 POST multipart 表单到 booking 站，返回 JSON。

    :raises RuntimeError: 被 WAF 拦截、网络失败或返回非 JSON
    """
    import json

    def _do():
        browser = _ensure(se, timeout)
        status, text = browser.post(path, fields, timeout)
        if status == 0:
            # 页面可能已失效（网络断开等），丢弃浏览器，下次重建
            _close_current()
        return status, text

    with _lock:
        status, text = _executor.submit(_do).result()
    if status != 200:
        raise RuntimeError(f"POST {path} 失败（HTTP {status}）: {text[:120]}")
    try:
        return json.loads(text)
    except ValueError:
        raise RuntimeError(f"POST {path} 返回非 JSON: {text[:120]}") from None


@atexit.register
def _shutdown() -> None:
    try:
        _executor.submit(_close_current).result(timeout=10)
    except Exception:
        pass
