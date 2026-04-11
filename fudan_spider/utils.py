"""
公共工具模块
"""

import os
import requests


def bark_notify(title: str, body: str, bark_url: str = None) -> bool:
    """
    通过 Bark 发送 iOS 推送通知。

    :param title: 通知标题
    :param body:  通知内容
    :param bark_url: Bark 推送 URL，优先使用传入值，否则读取环境变量 BARK_URL
    :return: 是否发送成功
    """
    url = bark_url or os.getenv("BARK_URL")
    if not url:
        raise ValueError("未设置 BARK_URL，请在环境变量或 .env 中配置")
    url = url.rstrip("/")
    resp = requests.get(f"{url}/{title}/{body}", timeout=10)
    return resp.status_code == 200
