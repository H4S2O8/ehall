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


def login_booking(uis_session: Session | None = None) -> Session:
    """
    完成 booking.fudan.edu.cn 的 SSO 登录。

    booking 有独立 session（reservation_uid / reservation_vd），
    需要以 /reservation/api/login/cas 作为 CAS service 换取。

    优先复用已有 UIS Session（只做一次 CAS ticket 换取，不重走密码/MFA）；
    未传入时才完整走登录流程。这样可以避免频繁触发风控。

    :param uis_session: 已通过 fudan_spider.uis.login() 获得的 Session（可选）。
                        传入时直接复用，会在原 Session 上追加 booking cookies。
                        传 None 时重新完整登录。
    :returns: 同一个 Session（已追加 booking cookies）
    """
    from fudan_spider.uis import login as _uis_login
    import os

    cas_service = f"{BOOKING_BASE}/reservation/api/login/cas"

    if uis_session is not None:
        # ── 复用已有 UIS session：让 CAS 为新 service 签发 ticket ──
        # id.fudan.edu.cn 已有 SSO session，直接请求新 service 的 ticket
        se = uis_session
        r = se.get(
            "https://id.fudan.edu.cn/authserver/login",
            params={"service": cas_service},
            allow_redirects=True,
        )
        # 如果 booking 已经有 reservation_uid，直接返回
        if any(c.name == "reservation_uid" for c in se.cookies):
            se.headers["Referer"] = (
                f"{BOOKING_BASE}/reservation/fe/site/special/special?id={TOPIC_ID}"
            )
            return se
        # 否则说明 UIS session 已过期，回退到完整登录
    
    # ── 完整登录（首次 or UIS session 过期）────────────────────
    se = _uis_login(
        username   = os.getenv("fudan_username"),
        password   = os.getenv("fudan_password"),
        otp_secret = os.getenv("fudan_otp_secret", ""),
        service    = cas_service,
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


def book_resource(
    se: Session,
    group_id: int,
    sub_resource_ids: list[int],
    period_id: int,
    date: str | datetime.date,
    phone: str,
    number: int = 1,
) -> dict:
    """
    预约场地（提交预约申请）。

    接口: POST /reservation/site/resource/launch
    数据格式: multipart/form-data

    :param group_id:          父场馆 ID（如乒乓球馆 group_id=1119）
    :param sub_resource_ids:  所有子场地 ID 列表（一次性传全，系统分配空闲场地）
    :param period_id:         时段 ID（从 get_schedule 的 time_slots 获取）
    :param date:              预约日期，格式 "YYYY-MM-DD" 或 datetime.date
    :param phone:             联系手机号（必填）
    :param number:            预约人数，默认 1
    :returns: API 返回的 d 字段，成功时 {"is_relate": False, "process_url": "", "process_id": 0}
    :raises RuntimeError: 预约失败时抛出，含错误信息
    """
    import json as _json

    if isinstance(date, datetime.date):
        date = date.isoformat()

    data = _json.dumps([{
        "resource_ids": sub_resource_ids,
        "group_id":     group_id,
        "period":       [{"date": date, "period_id": period_id}],
        "number":       number,
    }], ensure_ascii=False)

    data_colle = _json.dumps([{
        "name":   "手机号",
        "value":  phone,
        "verify": None,
        "type":   "mobile",
    }], ensure_ascii=False)

    captcha = _json.dumps({"token": "", "pointJson": ""})

    r = se.post(
        f"{BOOKING_BASE}/reservation/site/resource/launch",
        data={
            "data":       data,
            "data_colle": data_colle,
            "collective": "0",
            "captcha":    captcha,
        },
    )
    r.raise_for_status()
    body = r.json()
    if body.get("e") != "OK":
        raise RuntimeError(f"预约失败: {body.get('m') or body}")
    return body["d"]
