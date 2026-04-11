"""
zlapp.fudan.edu.cn 用电 API
- SSO 登录（复用 UIS 已认证 session）
- 查询剩余电量 / 宿舍信息
- 查询充值历史
"""

import re
from html import unescape
from requests import Session

BASE = "https://zlapp.fudan.edu.cn"


def zlapp_sso_login(session: Session) -> None:
    """
    利用已登录的 UIS session 完成 zlapp CAS SSO 认证。
    认证成功后 session 的 cookie 将包含 zlapp 的登录态。

    若 session 已处于登录态则直接返回（幂等）。
    """
    # 先探活：如果已登录则直接返回
    r = session.get(f"{BASE}/fudanelec/wap/default/info",
                    timeout=8, allow_redirects=False)
    if r.status_code == 200:
        try:
            if r.json().get("e") == 0:
                return
        except Exception:
            pass

    # 触发 CAS：访问 id.fudan.edu.cn，获取含 ticket 的跳转页
    service_url = f"{BASE}/a_fudanzlapp/api/sso/index?sso=1"
    r1 = session.get(
        "https://id.fudan.edu.cn/idp/authCenter/authenticate",
        params={"service": service_url},
        timeout=10,
        allow_redirects=True,
    )

    # 解析 locationValue（HTML 实体需 unescape）
    m = re.search(r'locationValue\s*=\s*"([^"]+)"', r1.text)
    if not m:
        raise RuntimeError(f"zlapp SSO 失败：未找到 ticket，响应: {r1.text[:300]}")

    ticket_url = unescape(m.group(1))

    # 用正确的 ticket URL 完成回调
    session.get(ticket_url, timeout=10, allow_redirects=True)


def get_electric_info(session: Session) -> dict:
    """
    查询宿舍剩余电量及基本信息。

    自动处理 SSO 登录（未登录时触发一次认证）。

    返回结构示例：
        {
          "campus":      "江湾",
          "building":    "15号楼",
          "room":        "323",
          "surplus_kwh": 23.08,
          "used_kwh":    3360.4,
          "total_kwh":   3383.48
        }
    """
    zlapp_sso_login(session)
    r = session.get(f"{BASE}/fudanelec/wap/default/info", timeout=10)
    r.raise_for_status()
    body = r.json()
    if body.get("e") != 0:
        raise RuntimeError(f"get_electric_info 失败: {body}")
    d = body["d"]
    return {
        "campus":      d.get("xq", ""),
        "building":    d.get("ssmc", ""),
        "room":        d.get("fjmc", ""),
        "surplus_kwh": d.get("fj_surplus", 0),
        "used_kwh":    d.get("fj_used", 0),
        "total_kwh":   d.get("fj_all", 0),
    }


def get_recharge_history(session: Session, limit: int = 10) -> list[dict]:
    """
    查询宿舍电费充值历史记录。

    自动处理 SSO 登录。

    :param limit: 最多返回条数（默认 10）

    返回结构示例：
        [
          {
            "time":    "2026-01-13 23:09:21",
            "amount":  10,
            "room":    "江湾/江湾/15号楼/323",
            "campus":  "江湾"
          },
          ...
        ]
    """
    zlapp_sso_login(session)
    r = session.get(f"{BASE}/fudanelec/wap/default/his", timeout=10)
    r.raise_for_status()
    body = r.json()
    if body.get("e") != 0:
        raise RuntimeError(f"get_recharge_history 失败: {body}")
    d = body.get("d", {})
    records = []
    for i in range(min(limit, len(d))):
        item = d.get(str(i), {})
        records.append({
            "time":   item.get("JYSJ", ""),
            "amount": item.get("money", 0),
            "room":   item.get("room", ""),
            "campus": item.get("xq", ""),
        })
    return records
