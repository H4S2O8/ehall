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


def make_storage_state(se: Session, path: str) -> str:
    """
    将 requests Session 的 cookies 转成 Playwright storage state JSON 文件。

    主要处理：
      - usk cookie 必须设到 .id.fudan.edu.cn，才能让 Playwright 在访问
        id.fudan.edu.cn（UIS SSO）时自动携带，从而让 workflow5 识别当前用户。
      - 其他 booking cookies domain 保持 booking.fudan.edu.cn。

    :param se:   login_booking() 返回的 Session
    :param path: 输出的 JSON 文件路径
    :returns:    path（方便链式使用）
    """
    import json as _json

    cookies = []
    for c in se.cookies:
        domain = c.domain or ""
        if c.name == "usk" or "id.fudan.edu.cn" in domain:
            domain = ".id.fudan.edu.cn"
        elif not domain:
            domain = "booking.fudan.edu.cn"
        cookies.append({
            "name":     c.name,
            "value":    c.value,
            "domain":   domain,
            "path":     c.path or "/",
            "sameSite": "Lax",
            "secure":   False,
            "httpOnly": False,
            "expires":  -1,
        })
    with open(path, "w") as f:
        _json.dump({"cookies": cookies, "origins": []}, f)
    return path


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
        raise RuntimeError(f"launch 失败: {body.get('m') or body}")
    return body["d"]


async def fill_workflow_form(
    process_url: str,
    storage_state: str,
    major: str,
    email: str,
    phone: str,
    activity_desc: str,
    application_file: str | None = None,
) -> None:
    """
    在 workflow5 工作流页面填写活动室预约申请表并提交。

    需要先调用 launch_resource() 获取 process_url，再调用本函数。
    本函数依赖 Playwright（playwright.async_api）。

    :param process_url:       launch_resource 返回的 process_url
    :param storage_state:     Playwright storage state JSON 文件路径（含 booking cookies）
    :param major:             专业代码（如 "081200"）
    :param email:             邮箱
    :param phone:             手机号
    :param activity_desc:     活动简介（含参与人数）
    :param application_file:  申请表扫描件路径（台球/琴房个人申请可不传）
    :raises RuntimeError:     提交失败时抛出
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=storage_state)
        page = await ctx.new_page()

        await page.goto(process_url, wait_until="networkidle")
        await page.wait_for_timeout(1500)

        # 处理"重新开始还是继续填写"弹窗
        restart_btn = page.get_by_role("button", name="重新开始")
        if await restart_btn.count() > 0:
            await restart_btn.click()
            await page.wait_for_timeout(1000)

        # 等待表单字段渲染（最多 15s）
        await page.wait_for_selector(
            "input[placeholder='请输入专业'], textarea[placeholder='请输入专业']",
            timeout=15000,
        )

        # 填写表单字段
        await page.get_by_role("textbox", name="请输入专业").click()
        await page.get_by_role("textbox", name="请输入专业").fill(major)

        await page.get_by_role("textbox", name="请输入邮箱").click()
        await page.get_by_role("textbox", name="请输入邮箱").fill(email)

        await page.get_by_role("textbox", name="请输入手机号").click()
        await page.get_by_role("textbox", name="请输入手机号").fill(phone)

        await page.get_by_role("textbox", name="（需包含活动简介和参与人数）").click()
        await page.get_by_role("textbox", name="（需包含活动简介和参与人数）").fill(activity_desc)

        # 上传文件（可选）
        import os as _os
        if application_file and _os.path.exists(application_file):
            upload_btn = page.get_by_role("button", name="点击上传含负责老师签字（盖章）的申请表扫描件")
            if await upload_btn.count() > 0:
                async with page.expect_file_chooser() as fc_info:
                    await upload_btn.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(application_file)
                await page.wait_for_timeout(2000)

        # 立即提交
        submit_btn = page.get_by_role("button", name="立即提交")
        if await submit_btn.count() == 0:
            await browser.close()
            raise RuntimeError("找不到「立即提交」按钮")
        await submit_btn.click()
        await page.wait_for_timeout(1500)

        # 确认弹窗
        ok_btn = page.get_by_role("button", name="确认")
        if await ok_btn.count() > 0:
            await ok_btn.click()
            await page.wait_for_timeout(2000)

        # 检查是否有错误提示（用更精确的选择器，避免误匹配"删除"按钮）
        error_msg = await page.evaluate("""
            () => {
                const el = document.querySelector(
                    '.n-alert--error-type, .error-msg'
                );
                return el ? el.textContent.trim() : null;
            }
        """)
        await browser.close()

        if error_msg:
            raise RuntimeError(f"提交失败: {error_msg}")


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


async def cancel_reserve(
    storage_state: str,
    reserve_id: Optional[int] = None,
) -> None:
    """
    在「我的预约」页面取消预约。

    通过 Playwright 打开 myReservation 页面，点击「取消预约」并确认。
    如果页面上有多条预约，可传入 reserve_id 精确匹配对应行（暂未实现，
    默认取消第一条）。

    :param storage_state: Playwright storage state JSON 文件路径
    :param reserve_id:    预约 ID（保留参数，当前版本取消第一条）
    :raises RuntimeError: 找不到取消按钮或取消失败时抛出
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=storage_state)
        page = await ctx.new_page()

        await page.goto(
            f"{BOOKING_BASE}/reservation/fe/site/myReservation",
            wait_until="networkidle",
        )
        await page.wait_for_timeout(1500)

        cancel_btn = page.get_by_role("button", name="取消预约")
        if await cancel_btn.count() == 0:
            await browser.close()
            raise RuntimeError("找不到「取消预约」按钮，可能已无可取消的预约")

        await cancel_btn.first.click()
        await page.wait_for_timeout(800)

        confirm_btn = page.get_by_role("button", name="确认")
        if await confirm_btn.count() > 0:
            await confirm_btn.click()
            await page.wait_for_timeout(1500)

        await browser.close()
