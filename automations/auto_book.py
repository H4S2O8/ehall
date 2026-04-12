"""
自动预约脚本
============
每天凌晨（或指定时间）运行，查询明天指定场馆的空闲时段并自动提交预约。

支持两种场馆类型：
  - sports  体育场馆（乒乓球、羽毛球、篮球等，调用 book_resource）
  - activity 活动室类场馆（需要 workflow5 审批表单，调用 launch_resource）

配置方式（通过环境变量，写在 .env 中）：
  BOOK_VENUE_TYPE      场馆类型，"sports" 或 "activity"（默认 sports）
  BOOK_RESOURCE_ID     父场馆 ID（sports 模式用）或 group_id（activity 模式用）
  BOOK_SUB_IDS         子场地 ID 列表，英文逗号分隔（sports 模式用，留空则自动查询）
  BOOK_PREFER_TIMES    期望时段列表，英文逗号分隔，格式如 "18:00-20:00,20:00-22:00"
                       按顺序匹配第一个空闲的时段；留空则取第一个空闲时段
  BOOK_DATE_OFFSET     预约哪一天，相对于今天的偏移天数（默认 1，即明天）
  BOOK_NUMBER          预约人数（默认 1）
  BOOK_MAX_RETRIES     失败时重试次数（默认 3）
  BOOK_RETRY_INTERVAL  重试间隔秒数（默认 30）

  # activity 模式额外需要（也可直接读 fudan_* 变量）：
  # fudan_major / fudan_email / fudan_phone / fudan_activity_desc
  # fudan_application_file（可选）

运行方式：
  uv run python automations/auto_book.py

建议配合系统 crontab 或 CodeBuddy Automation 在每天 07:00 左右运行。
"""

import datetime
import logging
import os
import sys
import time

# 确保项目根目录在 sys.path，无论从哪里调用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("auto_book")


# ── 读取配置 ────────────────────────────────────────────────────────────────

VENUE_TYPE       = os.getenv("BOOK_VENUE_TYPE", "sports").strip().lower()
RESOURCE_ID      = int(os.getenv("BOOK_RESOURCE_ID", "0"))
SUB_IDS_RAW      = os.getenv("BOOK_SUB_IDS", "").strip()
PREFER_TIMES_RAW = os.getenv("BOOK_PREFER_TIMES", "").strip()
DATE_OFFSET      = int(os.getenv("BOOK_DATE_OFFSET", "1"))
NUMBER           = int(os.getenv("BOOK_NUMBER", "1"))
MAX_RETRIES      = int(os.getenv("BOOK_MAX_RETRIES", "3"))
RETRY_INTERVAL   = int(os.getenv("BOOK_RETRY_INTERVAL", "30"))

# 解析子场地 ID 列表（sports 模式）
SUB_IDS: list[int] = (
    [int(x.strip()) for x in SUB_IDS_RAW.split(",") if x.strip()]
    if SUB_IDS_RAW else []
)

# 解析期望时段列表，如 ["18:00-20:00", "20:00-22:00"]
PREFER_TIMES: list[str] = (
    [t.strip() for t in PREFER_TIMES_RAW.split(",") if t.strip()]
    if PREFER_TIMES_RAW else []
)


def _pick_slot(available: list[dict]) -> dict | None:
    """从空闲时段中按 PREFER_TIMES 优先级选出最佳时段，无偏好则取第一个。"""
    if not available:
        return None
    if not PREFER_TIMES:
        return available[0]
    for prefer in PREFER_TIMES:
        for slot in available:
            if slot.get("str_time") == prefer:
                return slot
    # 没有匹配到偏好时段，退而求其次取第一个
    log.warning("没有匹配偏好时段 %s，使用第一个空闲时段", PREFER_TIMES)
    return available[0]


def _notify(msg: str) -> None:
    """发送通知（Bark），BARK_URL 未配置时只打日志。"""
    bark_url = os.getenv("BARK_URL", "").strip()
    if not bark_url:
        return
    try:
        import urllib.request, urllib.parse
        title = urllib.parse.quote("预约通知")
        body  = urllib.parse.quote(msg)
        urllib.request.urlopen(f"{bark_url}/{title}/{body}", timeout=5)
    except Exception as e:
        log.warning("Bark 通知失败: %s", e)


# ── 体育场馆预约流程 ─────────────────────────────────────────────────────────

def _run_sports(target_date: datetime.date) -> None:
    from fudan_spider.apis.booking import (
        login_booking,
        get_available_slots,
        book_resource,
    )

    if RESOURCE_ID == 0:
        raise ValueError("BOOK_RESOURCE_ID 未配置")

    log.info("登录 booking.fudan.edu.cn ...")
    se = login_booking()

    log.info("查询场馆 %d 在 %s 的空闲时段 ...", RESOURCE_ID, target_date)
    available = get_available_slots(se, RESOURCE_ID, target_date)
    log.info("空闲时段: %s", [s["str_time"] for s in available])

    slot = _pick_slot(available)
    if slot is None:
        msg = f"{target_date} 场馆 {RESOURCE_ID} 无空闲时段"
        log.warning(msg)
        _notify(msg)
        return

    # 子场地 ID：优先用配置，否则用 slot 里查到的
    sub_ids = SUB_IDS if SUB_IDS else [slot["sub_resource_id"]]
    phone   = os.getenv("fudan_phone", "")

    log.info(
        "准备预约: %s %s sub_ids=%s time_id=%d",
        target_date, slot["str_time"], sub_ids, slot["time_id"],
    )
    result = book_resource(
        se,
        group_id         = RESOURCE_ID,
        sub_resource_ids = sub_ids,
        period_id        = slot["time_id"],
        date             = target_date,
        phone            = phone,
        number           = NUMBER,
    )

    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        msg_   = result.get("message", "")
        log.warning("预约未成功: %s — %s", reason, msg_)
        _notify(f"预约失败({reason}): {msg_}")
        return

    success_msg = f"预约成功: {target_date} {slot['str_time']}"
    log.info(success_msg)
    _notify(success_msg)


# ── 活动室预约流程 ──────────────────────────────────────────────────────────

def _run_activity(target_date: datetime.date) -> None:
    from fudan_spider.apis.booking import (
        login_booking,
        get_calendar,
        launch_resource,
        fill_workflow_form,
    )
    from fudan_spider.uis import login as uis_login

    if RESOURCE_ID == 0:
        raise ValueError("BOOK_RESOURCE_ID 未配置")

    username    = os.getenv("fudan_username")
    password    = os.getenv("fudan_password")
    otp_secret  = os.getenv("fudan_otp_secret", "")
    WF_BASE     = "https://workflow5.fudan.edu.cn"

    log.info("登录 booking.fudan.edu.cn ...")
    booking_se = login_booking()

    log.info("查询活动室 %d 在 %s 的时段 ...", RESOURCE_ID, target_date)
    cal = get_calendar(booking_se, RESOURCE_ID, target_date)

    date_str   = target_date.isoformat()
    time_slots = {str(t["id"]): t for t in cal["time_slots"]}
    day_avail  = cal["availability"].get(date_str, {})

    # 汇总所有空闲时段 (status=0) 并展平
    available = []
    for sub_id_str, sub_slots in day_avail.items():
        sub_name = next(
            (r["name"] for r in cal["sub_resources"] if str(r["id"]) == sub_id_str),
            sub_id_str,
        )
        for tid_str, info in sub_slots.items():
            if info.get("status") == 0 and info.get("num", "0") != "0":
                t = time_slots.get(tid_str, {})
                available.append({
                    "sub_resource_id":   int(sub_id_str),
                    "sub_resource_name": sub_name,
                    "time_id":           int(tid_str),
                    "str_time":          t.get("str_time", tid_str),
                })

    log.info("空闲时段: %s", [s["str_time"] for s in available])
    slot = _pick_slot(available)
    if slot is None:
        msg = f"{target_date} 活动室 {RESOURCE_ID} 无空闲时段"
        log.warning(msg)
        _notify(msg)
        return

    log.info("准备预约: %s %s sub_id=%d time_id=%d",
             target_date, slot["str_time"], slot["sub_resource_id"], slot["time_id"])
    result = launch_resource(
        booking_se,
        resource_id = slot["sub_resource_id"],
        period_id   = slot["time_id"],
        date        = target_date,
        number      = NUMBER,
    )

    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        msg_   = result.get("message", "")
        log.warning("预约未成功: %s — %s", reason, msg_)
        _notify(f"预约失败({reason}): {msg_}")
        return

    process_id = result.get("process_id")
    log.info("launch 成功，process_id=%s，开始填写 workflow5 审批表单 ...", process_id)

    uis_se = uis_login(
        username   = username,
        password   = password,
        otp_secret = otp_secret,
        service    = f"{WF_BASE}/api/login/cas",
    )
    fill_workflow_form(
        uis_session      = uis_se,
        reserve_id       = process_id,
        major            = os.getenv("fudan_major", ""),
        email            = os.getenv("fudan_email", ""),
        phone            = os.getenv("fudan_phone", ""),
        activity_desc    = os.getenv("fudan_activity_desc", "学习讨论"),
        application_file = os.getenv("fudan_application_file"),
        booking_session  = booking_se,
    )

    success_msg = f"活动室预约成功: {target_date} {slot['str_time']} (process_id={process_id})"
    log.info(success_msg)
    _notify(success_msg)


# ── 主入口 ──────────────────────────────────────────────────────────────────

def main() -> None:
    if RESOURCE_ID == 0:
        log.error("请在 .env 中配置 BOOK_RESOURCE_ID")
        sys.exit(1)

    target_date = datetime.date.today() + datetime.timedelta(days=DATE_OFFSET)
    log.info(
        "开始自动预约: type=%s resource_id=%d date=%s prefer=%s",
        VENUE_TYPE, RESOURCE_ID, target_date, PREFER_TIMES or "任意空闲时段",
    )

    runner = _run_sports if VENUE_TYPE == "sports" else _run_activity

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            runner(target_date)
            break
        except Exception as e:
            log.error("第 %d/%d 次尝试失败: %s", attempt, MAX_RETRIES, e, exc_info=True)
            if attempt < MAX_RETRIES:
                log.info("等待 %d 秒后重试 ...", RETRY_INTERVAL)
                time.sleep(RETRY_INTERVAL)
            else:
                _notify(f"自动预约彻底失败: {e}")
                sys.exit(1)


if __name__ == "__main__":
    main()
