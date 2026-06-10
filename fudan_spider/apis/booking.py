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
from typing import Optional
from requests import Session

BOOKING_BASE = "https://booking.fudan.edu.cn"
TOPIC_ID     = 48  # 体育场馆


def _load_chrome_waf_cookies() -> dict:
    """
    从本机 Chrome 读取 booking.fudan.edu.cn 的 WAF 质询 cookie。
    WAF（瑞数）会检查 TLS 指纹，纯 requests session 无法通过；
    用真实浏览器已解过质询的 cookie 注入后可绕过。
    """
    try:
        import rookiepy
        waf_names = {"7GdWaAWutylUO", "7GdWaAWutylUP", "0a2b5cfd50f6f39396"}
        cookies = {
            c["name"]: c["value"]
            for c in rookiepy.chrome(["booking.fudan.edu.cn"])
            if c["name"] in waf_names
        }
        return cookies
    except Exception:
        return {}


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
    import fudan_spider.uis as _uis_mod
    from fudan_spider.uis import login as _uis_login
    import os

    cas_service = f"{BOOKING_BASE}/reservation/api/login/cas"
    waf_cookies = _load_chrome_waf_cookies()

    def _patched_build_session():
        se = _uis_mod._orig_build_session()
        for name, val in waf_cookies.items():
            se.cookies.set(name, val, domain="booking.fudan.edu.cn", path="/")
        return se

    # 临时注入 WAF cookies 到 build_session（仅当有 cookie 时）
    if waf_cookies and not hasattr(_uis_mod, "_orig_build_session"):
        _uis_mod._orig_build_session = _uis_mod.build_session
        _uis_mod.build_session = _patched_build_session

    try:
        if uis_session is not None:
            # ── 复用已有 UIS session：让 CAS 为新 service 签发 ticket ──
            se = uis_session
            for name, val in waf_cookies.items():
                se.cookies.set(name, val, domain="booking.fudan.edu.cn", path="/")
            se.get(
                "https://id.fudan.edu.cn/authserver/login",
                params={"service": cas_service},
                allow_redirects=True,
            )
            if any(c.name == "reservation_uid" for c in se.cookies):
                se.headers["Referer"] = (
                    f"{BOOKING_BASE}/reservation/fe/site/special/special?id={TOPIC_ID}"
                )
                return se
            # UIS session 已过期，回退到完整登录

        # ── 完整登录（首次 or UIS session 过期）────────────────────
        se = _uis_login(
            username   = os.getenv("fudan_username"),
            password   = os.getenv("fudan_password"),
            otp_secret = os.getenv("fudan_otp_secret", ""),
            service    = cas_service,
        )
    finally:
        if hasattr(_uis_mod, "_orig_build_session"):
            _uis_mod.build_session = _uis_mod._orig_build_session
            del _uis_mod._orig_build_session

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
        params={"id": topic_id, "pageSize": 200},
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


def get_calendar(
    se: Session,
    resource_id: int,
    date: str | datetime.date | None = None,
) -> dict:
    """
    查询指定场馆某天的时段占用情况（适用于活动室类场馆，如 id=751）。

    接口: GET /reservation/site/resource/calendar
    与 get_schedule 的区别：
      - 返回 status 字段（0=空闲，非0=占用），而非 occupy 字段
      - date 参数需序列化为 JSON {"start_date": ..., "end_date": ...}

    :param resource_id: 场馆 ID（如活动室 group_id=751）
    :param date:        查询日期，默认今天
    :returns: {
        "time_slots": [{"id": 3314, "str_time": "08:30-10:30", ...}, ...],
        "sub_resources": [{"id": 752, "name": "江湾光华mall学生活动中心-多功能厅"}, ...],
        "availability": {
            "2026-04-12": {
                "752": {"3314": {"status": 0, "total": 1, "num": "1"}, ...},
                ...
            }
        }
    }
    """
    import json as _json

    if date is None:
        date = datetime.date.today()
    if isinstance(date, datetime.date):
        date = date.isoformat()

    r = se.get(
        f"{BOOKING_BASE}/reservation/site/resource/calendar",
        params={
            "id":         resource_id,
            "collective": 0,
            "date":       _json.dumps({"start_date": date, "end_date": date}),
        },
    )
    r.raise_for_status()
    body = r.json()
    if body.get("e") != "OK":
        raise RuntimeError(f"resource/calendar 失败: {body.get('m')}")

    d = body["d"]
    return {
        "time_slots":    d.get("time", []),
        "sub_resources": d.get("resource", []),
        "availability":  d.get("data", {}),
    }


def launch_resource(
    se: Session,
    resource_id: int,
    period_id: int,
    date: str | datetime.date,
    number: int = 1,
) -> dict:
    """
    提交场地预约（适用于活动室类场馆，如 id=751）。

    接口: POST /reservation/site/resource/launch
    与 book_resource 的区别：
      - 使用 resource_id（单个子场地 ID），而非 resource_ids 列表
      - data_colle 为空数组（表单字段在后续工作流中填写）
      - 返回 is_relate=True 时，需访问 process_url 继续在工作流填表

    :param resource_id: 子场地 ID（从 get_calendar 的 sub_resources 获取）
    :param period_id:   时段 ID（从 get_calendar 的 time_slots 获取）
    :param date:        预约日期
    :param number:      预约人数，默认 1
    :returns: {
        "is_relate":  True,
        "process_url": "https://workflow5.fudan.edu.cn/...",
        "process_id":  17938,
    }
    :raises RuntimeError: 预约失败时抛出
    """
    import json as _json

    if isinstance(date, datetime.date):
        date = date.isoformat()

    data = _json.dumps([{
        "resource_id": str(resource_id),
        "period":      [{"date": date, "period_id": period_id}],
        "number":      number,
    }], ensure_ascii=False)

    captcha = _json.dumps({"token": "", "pointJson": ""})

    r = se.post(
        f"{BOOKING_BASE}/reservation/site/resource/launch",
        data={
            "data":       data,
            "data_colle": "[]",
            "collective": "0",
            "captcha":    captcha,
        },
    )
    r.raise_for_status()
    body = r.json()
    if body.get("e") != "OK":
        msg = body.get("m") or str(body)
        if "服务时间" in msg:
            return {"ok": False, "reason": "not_in_service_time", "message": msg}
        if "未结束的预约" in msg:
            return {"ok": False, "reason": "existing_reservation", "message": msg}
        raise RuntimeError(f"launch 失败: {msg}")
    return {**body["d"], "ok": True}


def fill_workflow_form(
    uis_session: Session,
    reserve_id: int,
    major: str,
    email: str,
    phone: str,
    activity_desc: str,
    application_file: str | None = None,
    booking_session: Session | None = None,
) -> None:
    """
    通过纯 requests 调用 workflow5 API 填写活动室预约申请表并提交。

    需要先调用 launch_resource() 获取 reserve_id（即 process_id），再调用本函数。
    uis_session 需已通过 workflow5 CAS 登录（service=https://workflow5.fudan.edu.cn/api/login/cas）。

    :param uis_session:       已完成 workflow5 SSO 登录的 requests Session
    :param reserve_id:        launch_resource 返回的 process_id
    :param major:             专业代码（如 "081200"）
    :param email:             邮箱
    :param phone:             手机号
    :param activity_desc:     活动简介（含参与人数）
    :param application_file:  申请表扫描件本地路径（可选，不传则上传 1×1 占位图）
    :param booking_session:   login_booking() 返回的 Session（用于查询预约详情填入表单）
                              不传时跳过 Input_22 字段
    :raises RuntimeError:     提交失败时抛出
    """
    import json as _json
    import os as _os
    import secrets
    import string
    import struct
    import zlib

    WF_BASE = "https://workflow5.fudan.edu.cn"
    APP_ID  = 361

    def _nanoid(size: int = 21) -> str:
        alphabet = string.ascii_letters + string.digits + "_-"
        return "".join(secrets.choice(alphabet) for _ in range(size))

    def _tiny_png() -> bytes:
        def chunk(t, d):
            c = t + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
                + chunk(b"IEND", b""))

    # ── 确保已登录 workflow5 ──────────────────────────────────────
    uis_session.post(f"{WF_BASE}/site/user/front-auth")
    r_user = uis_session.get(f"{WF_BASE}/site/user/baseinfo")
    r_user.raise_for_status()
    user = r_user.json()["d"]

    # ── 获取预约详情字符串（填入 Input_22）────────────────────────
    detail_info = ""
    if booking_session is not None:
        r_list = booking_session.get(
            f"{BOOKING_BASE}/reservation/site/appointment/appointment-list",
            params={"p": 1, "pageSize": 5, "type": 0},
        )
        r_list.raise_for_status()
        for item in (r_list.json() or {}).get("d", {}).get("data", []):
            if item.get("process_id") == reserve_id or item.get("is_cancel") == 1:
                for date_str, dets in item.get("detail", {}).items():
                    for det in dets:
                        detail_info = (
                            f"{item['resource_name'].split('_')[-1]} "
                            f"{date_str} {det['str_time']}"
                        )
                if detail_info:
                    break

    # ── 上传文件 ─────────────────────────────────────────────────
    referer = (
        f"{WF_BASE}/fe/taskCenter/matterApplication"
        f"?force=1&app_id={APP_ID}&reserve_id={reserve_id}&platform_id=43"
    )
    up_headers = {
        "Referer": f"{WF_BASE}/fe/taskCenter/matterApplication",
        "Origin":  WF_BASE,
    }
    if application_file and _os.path.exists(application_file):
        fname = _os.path.basename(application_file)
        with open(application_file, "rb") as fh:
            file_bytes = fh.read()
        mime = "application/pdf" if fname.lower().endswith(".pdf") else "image/png"
    else:
        fname      = "申请表.png"
        file_bytes = _tiny_png()
        mime       = "image/png"

    r_up = uis_session.post(
        f"{WF_BASE}/api/file/up",
        files={"upfile": (fname, file_bytes, mime)},
        headers=up_headers,
    )
    r_up.raise_for_status()
    up_body = r_up.json()
    if up_body.get("e") != "OK":
        raise RuntimeError(f"文件上传失败: {r_up.text}")
    file_token = up_body["d"]["token"]
    file_name  = up_body["d"]["name"]

    # ── 保存表单 ─────────────────────────────────────────────────
    wf_headers = {
        "Referer":          referer,
        "Origin":           WF_BASE,
        "X-Requested-With": "XMLHttpRequest",
    }
    form_data = _json.dumps({"454": {
        "User_6":   user.get("name", ""),
        "User_16":  user.get("depart_name", ""),
        "User_18":  user.get("number", ""),
        "Input_17": major,
        "Input_19": phone,
        "Input_20": email,
        "Input_22": detail_info,
        "Input_24": activity_desc,
        "File_27":  [{"id": _nanoid(), "token": file_token, "name": file_name,
                      "status": "success", "sign_status": 0}],
        "Link_30":  "链接",
    }}, ensure_ascii=False)

    r_save = uis_session.post(
        f"{WF_BASE}/site/app/save",
        data={"app_id": APP_ID, "department_id": 244,
              "form_data": form_data, "load_id[]": 0},
        headers=wf_headers,
    )
    r_save.raise_for_status()
    save_body = r_save.json()
    if save_body.get("e") != "OK":
        raise RuntimeError(f"app/save 失败: {r_save.text[:300]}")

    sess_id  = save_body["d"]["id"]
    assignee = {
        str(node["node_id"]): [a["id"] for a in node["assignee"]]
        for node in save_body["d"].get("assignee", [])
    }

    # ── 提交工作流 ────────────────────────────────────────────────
    r_start = uis_session.post(
        f"{WF_BASE}/site/app/start",
        data={"sess_id": sess_id, "data": _json.dumps({"assignee": assignee})},
        headers=wf_headers,
    )
    r_start.raise_for_status()
    start_body = r_start.json()
    if start_body.get("e") != "OK":
        raise RuntimeError(f"app/start 失败: {r_start.text[:300]}")


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
        msg = body.get("m") or str(body)
        if "服务时间" in msg:
            return {"ok": False, "reason": "not_in_service_time", "message": msg}
        if "未结束的预约" in msg:
            return {"ok": False, "reason": "existing_reservation", "message": msg}
        raise RuntimeError(f"预约失败: {msg}")
    return {**body["d"], "ok": True}


def cancel_reserve(
    se: Session,
    reserve_id: Optional[int] = None,
) -> None:
    """
    取消预约。

    调用 booking API 列出当前预约，取消第一条可取消的预约；
    若传入 reserve_id 则精确匹配对应记录。

    :param se:         login_booking() 返回的 Session（需持有 booking cookies）
    :param reserve_id: 预约 ID（可选，不传则取消列表中第一条可取消的记录）
    :raises RuntimeError: 找不到可取消的预约或取消失败时抛出
    """
    import json as _json

    r = se.get(
        f"{BOOKING_BASE}/reservation/site/appointment/appointment-list",
        params={"p": 1, "pageSize": 20, "type": 0},
    )
    r.raise_for_status()
    items = r.json().get("d", {}).get("data", [])

    target = None
    for item in items:
        if item.get("is_cancel") != 1:
            continue
        if reserve_id is None or item.get("id") == reserve_id:
            target = item
            break

    if target is None:
        raise RuntimeError("找不到可取消的预约记录")

    detail_ids = [
        det["id"]
        for dets in target["detail"].values()
        for det in dets
        if det.get("is_cancel")
    ]
    resp = se.post(
        f"{BOOKING_BASE}/reservation/site/appointment/appointment-cancel",
        data={
            "appointment_id":        target["id"],
            "appointment_detail_id": _json.dumps(detail_ids),
        },
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("e") != "OK":
        raise RuntimeError(f"取消预约失败: {body.get('m') or body}")
