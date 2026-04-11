"""
UIS 统一身份认证模块
https://uis.fudan.edu.cn/authserver/login
"""

import os
from requests import Session
from parsel import Selector

UIS_LOGIN_URL = "https://uis.fudan.edu.cn/authserver/login"


def build_session() -> Session:
    """创建并返回一个带有通用 Headers 的 Session"""
    se = Session()
    se.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    })
    return se


def get_hidden_inputs(se: Session) -> dict:
    """GET 登录页，解析并返回所有隐藏表单字段"""
    res = se.get(UIS_LOGIN_URL)
    res.raise_for_status()
    sel = Selector(res.text)
    names = sel.css("#casLoginForm > input[type=hidden]::attr(name)").getall()
    values = sel.css("#casLoginForm > input[type=hidden]::attr(value)").getall()
    return dict(zip(names, values))


def login(username: str = None, password: str = None) -> Session:
    """
    完成 UIS 登录，返回已认证的 Session。

    优先使用传入的参数，否则读取环境变量
    fudan_username / fudan_password（支持 .env 文件）。

    :raises AssertionError: 登录失败时抛出
    :raises RuntimeError: 触发图片验证码时抛出（需人工处理）
    """
    username = username or os.getenv("fudan_username")
    password = password or os.getenv("fudan_password")
    if not username or not password:
        raise ValueError(
            "未提供账号或密码，请设置环境变量 fudan_username / fudan_password，"
            "或在调用 login() 时显式传入。"
        )

    se = build_session()
    hidden = get_hidden_inputs(se)

    payload = {
        "username": username,
        "password": password,
        **hidden,
    }

    res = se.post(UIS_LOGIN_URL, data=payload)
    res.raise_for_status()

    if "needCaptcha" in res.url or "captcha" in res.text.lower():
        raise RuntimeError(
            "触发了图片验证码，自动登录暂不支持，请稍后重试或换个网络环境。"
        )

    assert "安全退出" in res.text, (
        "登录失败：响应中未找到【安全退出】字样。\n"
        f"当前 URL: {res.url}\n"
        f"响应片段: {res.text[:300]}"
    )

    return se
