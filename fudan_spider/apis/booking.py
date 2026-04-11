"""
体育场馆预约 API
服务地址: booking.fudan.edu.cn
专题 ID:  48（体育场馆网上预约）

已逆向接口:
  GET /api/topic/detail?id=<topic_id>
      → 专题详情（名称、简介、总预约数）

  GET /api/topic/resource-list?id=<topic_id>
      → 该专题下所有场馆列表
        每项: { base: { id, name, type, config, ... }, ... }

  GET /api/resource/large-screen?id=<resource_id>&date=YYYY-MM-DD
      → 指定场馆+日期的完整时段占用情况
        {
          "time":     [ { id, str_time, start_time, end_time }, ... ],
          "resource": [ { id, name }, ... ],    # 子场地列表
          "data": {
            "<sub_resource_id>": {
              "<time_id>": {
                "occupy":      true/false,       # 是否已占用
                "sign_status": 0/1,              # 0未签到/1已签到
                "user":        "姓*名",
                "content":     ""                # 占用原因
              }
            }
          }
        }

注意: 需要先用 login_booking() 获取带 booking session 的 Session，
      再调用其他接口，否则返回"无权访问"。
"""

import datetime
from requests import Session

BOOKING_BASE = "https://booking.fudan.edu.cn"
TOPIC_ID     = 48  # 体育场馆


def login_booking(uis_session: Session) -> Session:
    """
    在已有 UIS Session 的基础上完成 booking.fudan.edu.cn 的 SSO 登录。

    booking 有独立 session（reservation_uid / reservation_vd），
    需要以 /api/login/cas 作为 CAS service 重新登录换取。

    :param uis_session: 已通过 fudan_spider.uis.login() 获得的 Session
                        （直接传入，会在原 Session 上追加 booking cookies）
    :returns: 同一个 Session（已追加 booking cookies）
    """
    from fudan_spider.uis import login as _uis_login
    import os
    # 重新登录，service 指向 booking CAS 入口
    se = _uis_login(
        username   = os.getenv("fudan_username"),
        password   = os.getenv("fudan_password"),
        otp_secret = os.getenv("fudan_otp_secret", ""),
        service    = f"{BOOKING_BASE}/reservation/api/login/cas",
    )
    se.headers["Referer"] = (
        f"{BOOKING_BASE}/reservation/fe/site/special/special?id={TOPIC_ID}"
    )
    return se


def get_topic_detail(se: Session, topic_id: int = TOPIC_ID) -> dict:
    """
    获取专题详情。

    :returns: {
        "name":             "体育场馆网上预约",
        "visit_num":        586272,
        "appointment_num":  40382,
        "desc":             { "text": "<html>..." }
      }
    """
    r = se.get(
        f"{BOOKING_BASE}/reservation/api/topic/detail",
        params={"id": topic_id},
    )
    r.raise_for_status()
    body = r.json()
    if body.get("e") != "OK":
        raise RuntimeError(f"topic/detail 失败: {body.get('m')}")
    return body["d"]


def get_resource_list(se: Session, topic_id: int = TOPIC_ID) -> list[dict]:
    """
    获取专题下所有场馆资源列表。

    :returns: [
        {
          "id":   938,
          "name": "北区体育馆-羽毛球",
          "type": 6,
        },
        ...
      ]
    """
    r = se.get(
        f"{BOOKING_BASE}/reservation/api/topic/resource-list",
        params={"id": topic_id},
    )
    r.raise_for_status()
    body = r.json()
    if body.get("e") != "OK":
        raise RuntimeError(f"topic/resource-list 失败: {body.get('m')}")

    result = []
    for item in body.get("d", {}).get("data", []):
        base = item.get("base", {})
        result.append({
            "id":   base.get("id"),
            "name": base.get("name"),
            "type": base.get("type"),
        })
    return result


def get_schedule(
    se: Session,
    resource_id: int,
    date: str | datetime.date | None = None,
) -> dict:
    """
    查询指定场馆某天的时段占用情况。

    :param resource_id: 场馆 ID（从 get_resource_list 获取）
    :param date:        查询日期，默认今天，格式 "YYYY-MM-DD" 或 datetime.date
    :returns: {
        "time_slots": [
            { "id": 3800, "str_time": "08:00-09:00",
              "start": "08:00:00", "end": "09:00:00" },
            ...
        ],
        "sub_resources": [
            { "id": 939, "name": "1号场地A" },
            ...
        ],
        "availability": {
            "939": {               # 子场地 id
                "3800": {          # 时段 id
                    "occupy":      True,
                    "sign_status": 1,
                    "user":        "巨*波",
                    "content":     ""
                },
                ...
            }
        }
      }
    """
    if date is None:
        date = datetime.date.today()
    if isinstance(date, datetime.date):
        date = date.isoformat()

    r = se.get(
        f"{BOOKING_BASE}/reservation/api/resource/large-screen",
        params={"id": resource_id, "date": date},
    )
    r.raise_for_status()
    body = r.json()
    if body.get("e") != "OK":
        raise RuntimeError(f"resource/large-screen 失败: {body.get('m')}")

    d = body["d"]
    return {
        "time_slots": [
            {
                "id":       t["id"],
                "str_time": t["str_time"],
                "start":    t["start_time"],
                "end":      t["end_time"],
            }
            for t in d.get("time", [])
        ],
        "sub_resources": d.get("resource", []),
        "availability":  {
            str(rid): {
                str(tid): slot
                for tid, slot in slots.items()
            }
            for rid, slots in d.get("data", {}).items()
        },
    }


def get_available_slots(
    se: Session,
    resource_id: int,
    date: str | datetime.date | None = None,
) -> list[dict]:
    """
    获取指定场馆指定日期的**空闲**时段（occupy=False 的）。

    :returns: [
        {
          "sub_resource_id":   939,
          "sub_resource_name": "1号场地A",
          "time_id":           3804,
          "str_time":          "12:00-13:00",
        },
        ...
      ]
    """
    schedule = get_schedule(se, resource_id, date)
    time_map = {str(t["id"]): t for t in schedule["time_slots"]}
    sub_map  = {str(r["id"]): r["name"] for r in schedule["sub_resources"]}

    available = []
    for rid_str, slots in schedule["availability"].items():
        for tid_str, slot in slots.items():
            if not slot.get("occupy", True):
                t = time_map.get(tid_str, {})
                available.append({
                    "sub_resource_id":   int(rid_str),
                    "sub_resource_name": sub_map.get(rid_str, rid_str),
                    "time_id":           int(tid_str),
                    "str_time":          t.get("str_time", tid_str),
                })
    return available
