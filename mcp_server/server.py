"""
MCP Server - 复旦校园场馆预约工具集
Phase 3: 将 fudan_spider booking API 封装为 MCP Tools

启动方式:
    uv run --extra mcp python -m mcp_server.server
    # 或
    python -m mcp_server.server

环境变量（.env）:
    fudan_username       学号
    fudan_password       密码
    fudan_otp_secret     TOTP 密钥（可选）
    fudan_phone          手机号（预约体育场馆必填）
    fudan_major          专业代码（预约活动室必填，如 081200）
    fudan_email          邮箱（预约活动室必填）
    fudan_activity_desc  活动简介（预约活动室必填）

包含三组工具:

Part 0 - 校园卡 & 宿舍用电:
    card_get_info               查询一卡通余额与基本信息
    electricity_get_records     查询宿舍近期用电记录（my.fudan.edu.cn）
    electricity_get_remaining   查询宿舍当前剩余电量（zlapp.fudan.edu.cn）
    electricity_get_recharge_history  查询电费充值历史

Part 1 - 体育场馆（TOPIC_ID=48, /api/ 系 API）:
    sports_list_venues        查询所有体育场馆列表
    sports_get_availability   查询指定场馆未来 N 天空闲时段
    sports_book               预约体育场馆时段
    sports_cancel             取消体育场馆预约

Part 2 - 江湾生活园区台球室（新光华悦动馆, resource_id=751, sub_id=759）:
    billiards_get_availability  查询台球室未来 N 天空闲时段
    billiards_book              预约台球室时段（自动提交工作流表单）
    billiards_cancel            取消台球室预约
"""

import datetime
import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP
from requests import Session

# ── 全局 Session 缓存（lazy init，避免每次 tool call 重新登录）──────────
_booking_session: Optional[Session] = None
_uis_session: Optional[Session] = None   # 用于 workflow5 登录（活动室工作流）
_my_session: Optional[Session] = None    # 用于 my.fudan.edu.cn（一卡通、用电）
_zlapp_session: Optional[Session] = None # 用于 zlapp.fudan.edu.cn（剩余电量）


def _get_booking_session() -> Session:
    """获取（或重建）booking session。"""
    global _booking_session
    from fudan_spider.apis.booking import login_booking
    from fudan_spider.uis import login as uis_login

    if _booking_session is not None:
        # 简单心跳探活：能拿到列表则复用
        try:
            r = _booking_session.get(
                "https://booking.fudan.edu.cn/reservation/api/topic/detail",
                params={"id": 48},
                timeout=8,
            )
            if r.json().get("e") == "OK":
                return _booking_session
        except Exception:
            pass

    # 重新登录
    _booking_session = login_booking()
    return _booking_session


def _get_uis_session() -> Session:
    """获取（或重建）已登录 workflow5 的 UIS session。"""
    global _uis_session
    from fudan_spider.uis import login as uis_login

    WF_BASE = "https://workflow5.fudan.edu.cn"

    if _uis_session is not None:
        try:
            r = _uis_session.get(f"{WF_BASE}/site/user/baseinfo", timeout=8)
            if r.json().get("e") == "OK":
                return _uis_session
        except Exception:
            pass

    _uis_session = uis_login(
        username=os.getenv("fudan_username"),
        password=os.getenv("fudan_password"),
        otp_secret=os.getenv("fudan_otp_secret", ""),
        service=f"{WF_BASE}/api/login/cas",
    )
    return _uis_session


def _get_my_session() -> Session:
    """获取（或重建）my.fudan.edu.cn 的 UIS session（一卡通、用电）。"""
    global _my_session
    from fudan_spider.uis import login as uis_login

    if _my_session is not None:
        try:
            r = _my_session.get("https://my.fudan.edu.cn/", timeout=8, allow_redirects=False)
            # 已登录时返回 200，未登录时会 302 到 id.fudan.edu.cn
            if r.status_code == 200:
                return _my_session
        except Exception:
            pass

    _my_session = uis_login(
        username=os.getenv("fudan_username"),
        password=os.getenv("fudan_password"),
        otp_secret=os.getenv("fudan_otp_secret", ""),
        # 使用默认 service=https://my.fudan.edu.cn/
    )
    return _my_session


def _get_zlapp_session() -> Session:
    """获取（或重建）zlapp.fudan.edu.cn 的 session（剩余电量）。"""
    global _zlapp_session
    from fudan_spider.uis import login as uis_login
    from fudan_spider.apis.zlapp_electric import zlapp_sso_login

    if _zlapp_session is None:
        _zlapp_session = uis_login(
            username=os.getenv("fudan_username"),
            password=os.getenv("fudan_password"),
            otp_secret=os.getenv("fudan_otp_secret", ""),
        )

    # 探活：zlapp_sso_login 内部会检查是否已登录，未登录则自动完成 SSO
    zlapp_sso_login(_zlapp_session)
    return _zlapp_session


# ── FastMCP App ────────────────────────────────────────────────────────────
app = FastMCP("fudan-booking")


# ══════════════════════════════════════════════════════════════════════════
# Part 0  校园卡 & 宿舍用电
# ══════════════════════════════════════════════════════════════════════════

@app.tool()
def card_get_info() -> dict:
    """
    查询复旦一卡通基本信息与余额。

    返回示例:
        {
          "balance": "128.50",
          "status": "正常",
          "expire": "2027-09-01",
          "campuses": ["邯郸", "江湾"]
        }
    """
    from fudan_spider.apis.card import get_card_info
    se = _get_my_session()
    raw = get_card_info(se)
    # raw["data"] 是二维列表，第一行: [卡号, 姓名, 状态, 可用校区, 有效期, 余额]
    rows = raw.get("data", [])
    if not rows:
        return {}
    row = rows[0]
    return {
        "card_no":  row[0],
        "name":     row[1],
        "status":   row[2],
        "campuses": row[3],
        "expire":   row[4],
        "balance":  row[5],
    }


@app.tool()
def electricity_get_records(length: int = 10) -> list[dict]:
    """
    查询宿舍近期用电记录。

    :param length: 返回记录条数，默认 10 条，最多 100 条。

    返回示例:
        [
          {"date": "2026-04-11", "dorm": "某某楼 123", "kwh": "2.34"},
          ...
        ]
    """
    from fudan_spider.apis.electricity import get_electricity
    se = _get_my_session()
    raw = get_electricity(se, length=length)
    # raw["data"] 是二维列表 [[日期, 宿舍, 用电量], ...]
    rows = raw.get("data", [])
    return [{"date": r[0], "dorm": r[1], "kwh": r[2]} for r in rows]


@app.tool()
def electricity_get_remaining() -> dict:
    """
    查询宿舍当前剩余电量（来自 zlapp.fudan.edu.cn）。

    返回示例:
        {
          "campus":      "江湾",
          "building":    "15号楼",
          "room":        "323",
          "surplus_kwh": 23.08,
          "used_kwh":    3360.4,
          "total_kwh":   3383.48
        }

    surplus_kwh 即剩余电量（度），used_kwh 为已用，total_kwh 为账户总量。
    """
    from fudan_spider.apis.zlapp_electric import get_electric_info
    se = _get_zlapp_session()
    return get_electric_info(se)


@app.tool()
def electricity_get_recharge_history(limit: int = 10) -> list[dict]:
    """
    查询宿舍电费充值历史记录（来自 zlapp.fudan.edu.cn）。

    :param limit: 返回条数，默认 10 条。

    返回示例:
        [
          {
            "time":   "2026-01-13 23:09:21",
            "amount": 10,
            "room":   "江湾/江湾/15号楼/323",
            "campus": "江湾"
          },
          ...
        ]
    """
    from fudan_spider.apis.zlapp_electric import get_recharge_history
    se = _get_zlapp_session()
    return get_recharge_history(se, limit=limit)


# ══════════════════════════════════════════════════════════════════════════
# Part 1  体育场馆（TOPIC_ID=48）
# ══════════════════════════════════════════════════════════════════════════

@app.tool()
def sports_list_venues() -> list[dict]:
    """
    查询复旦大学体育场馆预约系统（专题 ID=48）中的所有场馆列表。

    返回示例:
        [
          {"id": 938, "name": "北区体育馆-羽毛球", "type": 6},
          {"id": 1119, "name": "北区体育馆-乒乓球", "type": 6},
          ...
        ]

    id 字段即后续调用 sports_get_availability / sports_book 所需的 resource_id。
    """
    from fudan_spider.apis.booking import get_resource_list
    se = _get_booking_session()
    return get_resource_list(se)


@app.tool()
def sports_get_availability(
    resource_id: int,
    days: int = 3,
) -> list[dict]:
    """
    查询指定体育场馆未来 N 天的空闲时段。

    :param resource_id: 场馆 ID，通过 sports_list_venues 获取。
    :param days:        查询未来天数，默认 3 天（含今天）。

    返回示例:
        [
          {
            "date": "2026-04-12",
            "sub_resource_id": 939,
            "sub_resource_name": "1号场地A",
            "time_id": 3804,
            "str_time": "12:00-13:00"
          },
          ...
        ]
    """
    from fudan_spider.apis.booking import get_available_slots
    se = _get_booking_session()

    today = datetime.date.today()
    result = []
    for i in range(days):
        date = today + datetime.timedelta(days=i)
        slots = get_available_slots(se, resource_id, date)
        for s in slots:
            s["date"] = date.isoformat()
            result.append(s)
    return result


@app.tool()
def sports_book(
    group_id: int,
    sub_resource_ids: list[int],
    period_id: int,
    date: str,
    phone: str = "",
    number: int = 1,
) -> dict:
    """
    预约体育场馆时段。

    :param group_id:         父场馆 ID（即 sports_list_venues 返回的 id）。
    :param sub_resource_ids: 子场地 ID 列表（从 sports_get_availability 的 sub_resource_id 获取，
                             可传多个让系统自动分配空闲场地）。
    :param period_id:        时段 ID（从 sports_get_availability 的 time_id 获取）。
    :param date:             预约日期，格式 "YYYY-MM-DD"。
    :param phone:            联系手机号。为空时自动读取环境变量 fudan_phone。
    :param number:           预约人数，默认 1。

    返回示例:
        {"is_relate": False, "process_url": "", "process_id": 0}
    """
    from fudan_spider.apis.booking import book_resource
    se = _get_booking_session()

    if not phone:
        phone = os.getenv("fudan_phone", "")
    if not phone:
        raise ValueError("请提供手机号 phone 参数，或在 .env 中设置 fudan_phone")

    result = book_resource(
        se,
        group_id=group_id,
        sub_resource_ids=sub_resource_ids,
        period_id=period_id,
        date=date,
        phone=phone,
        number=number,
    )
    if not result.get("ok", True):
        return result  # 透传 {ok, reason, message}
    return result


@app.tool()
def sports_cancel(reserve_id: Optional[int] = None) -> str:
    """
    取消体育场馆预约。

    :param reserve_id: 预约记录 ID（可选）。
                       不传则自动取消预约列表中第一条可取消的记录。

    返回: "取消成功"
    """
    from fudan_spider.apis.booking import cancel_reserve
    se = _get_booking_session()
    cancel_reserve(se, reserve_id)
    return "取消成功"


# ══════════════════════════════════════════════════════════════════════════
# Part 2  江湾生活园区台球室（新光华悦动馆）
#         resource_id=751（group），sub_resource_id=759（台球室）
# ══════════════════════════════════════════════════════════════════════════

_BILLIARDS_GROUP_ID = 751
_BILLIARDS_SUB_ID   = 759  # 新光华悦动馆（台球室）


@app.tool()
def billiards_get_availability(days: int = 3) -> list[dict]:
    """
    查询江湾生活园区新光华悦动馆（台球室）未来 N 天的空闲时段。

    :param days: 查询未来天数，默认 3 天（含今天）。

    返回示例:
        [
          {
            "date": "2026-04-12",
            "time_id": 3314,
            "str_time": "18:00-20:00",
            "status": 0
          },
          ...
        ]

    status=0 表示空闲可预约。
    """
    from fudan_spider.apis.booking import get_calendar
    se = _get_booking_session()

    today = datetime.date.today()
    result = []
    for i in range(days):
        date = today + datetime.timedelta(days=i)
        date_str = date.isoformat()
        cal = get_calendar(se, _BILLIARDS_GROUP_ID, date)

        time_map = {str(t["id"]): t for t in cal["time_slots"]}
        day_avail = cal["availability"].get(date_str, {})
        sub_avail = day_avail.get(str(_BILLIARDS_SUB_ID), {})

        for tid_str, slot in sub_avail.items():
            if slot.get("status", 1) == 0:
                t = time_map.get(tid_str, {})
                result.append({
                    "date":     date_str,
                    "time_id":  int(tid_str),
                    "str_time": t.get("str_time", tid_str),
                    "status":   0,
                })
    return result


@app.tool()
def billiards_book(
    period_id: int,
    date: str,
    major: str = "",
    email: str = "",
    phone: str = "",
    activity_desc: str = "",
    application_file: str = "",
) -> dict:
    """
    预约江湾生活园区新光华悦动馆（台球室）时段，并自动提交工作流审批表单。

    :param period_id:       时段 ID（从 billiards_get_availability 的 time_id 获取）。
    :param date:            预约日期，格式 "YYYY-MM-DD"。
    :param major:           专业代码（如 "081200"）。为空时读取环境变量 fudan_major。
    :param email:           邮箱。为空时读取环境变量 fudan_email。
    :param phone:           手机号。为空时读取环境变量 fudan_phone。
    :param activity_desc:   活动简介。为空时读取环境变量 fudan_activity_desc，默认"打台球"。
    :param application_file: 申请表扫描件本地路径（可选，不传则上传占位图）。

    返回示例:
        {
          "reserve_id": 17985,
          "process_id": 17985,
          "workflow_submitted": true
        }
    """
    from fudan_spider.apis.booking import launch_resource, fill_workflow_form

    # 参数回退到环境变量
    if not major:
        major = os.getenv("fudan_major", "")
    if not email:
        email = os.getenv("fudan_email", "")
    if not phone:
        phone = os.getenv("fudan_phone", "")
    if not activity_desc:
        activity_desc = os.getenv("fudan_activity_desc", "打台球")
    if not application_file:
        application_file = os.getenv("fudan_application_file", "").strip("'\"") or None

    for name, val in [("major", major), ("email", email), ("phone", phone)]:
        if not val:
            raise ValueError(f"请提供 {name} 参数，或在 .env 中设置 fudan_{name}")

    booking_se = _get_booking_session()
    uis_se = _get_uis_session()

    # Step 1: 提交预约
    result = launch_resource(booking_se, _BILLIARDS_SUB_ID, period_id, date)

    # 不在服务时间等非异常失败
    if not result.get("ok", True):
        return result  # 透传 {ok, reason, message}

    process_id = result.get("process_id", 0)

    # Step 2: 提交工作流表单
    workflow_submitted = False
    if result.get("is_relate") and process_id:
        fill_workflow_form(
            uis_session=uis_se,
            reserve_id=process_id,
            major=major,
            email=email,
            phone=phone,
            activity_desc=activity_desc,
            application_file=application_file or None,
            booking_session=booking_se,
        )
        workflow_submitted = True

    return {
        "reserve_id":         process_id,
        "process_id":         process_id,
        "is_relate":          result.get("is_relate", False),
        "workflow_submitted": workflow_submitted,
    }


@app.tool()
def billiards_cancel(reserve_id: Optional[int] = None) -> str:
    """
    取消台球室预约。

    :param reserve_id: 预约记录 ID（可选）。
                       不传则自动取消预约列表中第一条可取消的记录。

    返回: "取消成功"
    """
    from fudan_spider.apis.booking import cancel_reserve
    se = _get_booking_session()
    cancel_reserve(se, reserve_id)
    return "取消成功"


# ── 入口 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fudan Booking MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="传输方式：stdio（本地进程）或 sse（HTTP 远端，默认端口 8000）",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="SSE 监听地址（仅 sse 模式有效，默认 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="SSE 监听端口（仅 sse 模式有效，默认 8000）",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        app.run(transport="sse", host=args.host, port=args.port)
    else:
        app.run(transport="stdio")
