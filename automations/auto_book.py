"""
自动预约脚本
============
每天凌晨（或指定时间）运行，查询明天指定场馆的空闲时段并自动提交预约。

支持两种场馆类型：
  - sports  体育场馆（乒乓球、羽毛球、篮球等，调用 book_resource）
  - activity 活动室类场馆（需要 workflow5 审批表单，调用 launch_resource）

配置方式（通过环境变量，写在 .env 中）：

  # ── 推荐：按名字选场馆（自动填充 ID）──────────────────────────────────
  BOOK_VENUE_NAME      场馆名称，从 automations/venues.py 中的已知列表选填。
                       例如 "羽毛球-本部"、"台球室"、"badminton"。
                       设置后自动推断 BOOK_VENUE_TYPE / BOOK_RESOURCE_ID / BOOK_SUB_IDS，
                       无需手动查 ID。运行 `uv run python automations/venues.py` 查看完整列表。

  # ── 手动指定 ID（优先级高于 BOOK_VENUE_NAME）───────────────────────────
  BOOK_VENUE_TYPE      场馆类型，"sports" 或 "activity"（默认 sports）
  BOOK_RESOURCE_ID     父场馆 ID（sports 模式用）或 group_id（activity 模式用）
  BOOK_SUB_IDS         子场地 ID 列表，英文逗号分隔（sports 模式用，留空则自动查询）

  # ── 通用配置 ────────────────────────────────────────────────────────────
  BOOK_PREFER_TIMES    期望时段列表，英文逗号分隔，格式如 "18:00-20:00,20:00-22:00"
                       按顺序匹配第一个空闲的时段；留空则取第一个空闲时段
  BOOK_DATE_OFFSET     预约哪一天，相对于今天的偏移天数（默认 1，即明天）
  BOOK_NUMBER          预约人数（默认 1）

  # ── 脉冲抢占模式（Pulse Mode）────────────────────────────────────────
  # 在预约窗口开放时刻（BOOK_OPEN_TIME）附近密集发请求，越近整点越密集。
  # 脚本需在 BOOK_OPEN_TIME 前至少 BOOK_PULSE_BEFORE 秒启动。
  BOOK_OPEN_TIME       预约窗口开放的时刻，格式 "HH:MM"（默认 "07:00"）
  BOOK_PULSE_BEFORE    开放前多少秒开始发请求（默认 60）
  BOOK_PULSE_AFTER     开放后多少秒内继续发请求（默认 60）
  BOOK_PULSE_MAX       脉冲窗口内最多发多少次请求（默认 10）
                       间隔按 sinh 分布，越接近开放时刻越密集，成功即退出。

  # ── activity 模式额外需要（也可直接读 fudan_* 变量）─────────────────
  # fudan_major / fudan_email / fudan_phone / fudan_activity_desc
  # fudan_application_file（可选）

运行方式：
  uv run python automations/auto_book.py

建议在 BOOK_OPEN_TIME 前约 70 秒启动（如开放时间 07:00 则 06:58:50 启动）：
  crontab: 58 6 * * * sleep 50 && cd /path/to/ehall && uv run python automations/auto_book.py
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

from automations.venues import lookup as _venue_lookup

# 1. 先尝试按名字从字典解析
_venue_name = os.getenv("BOOK_VENUE_NAME", "").strip()
_venue_info = _venue_lookup(_venue_name) if _venue_name else None

if _venue_info and not os.getenv("BOOK_RESOURCE_ID"):
    # 字典命中且用户未手动覆盖 ID
    VENUE_TYPE  = _venue_info.venue_type
    RESOURCE_ID = _venue_info.resource_id
    _sub_default = _venue_info.sub_ids
    log_prefix  = f"[venue_name={_venue_name}]"
elif _venue_name and not _venue_info:
    # 名字写了但没找到
    import logging as _log_tmp
    _log_tmp.basicConfig()
    _log_tmp.getLogger("auto_book").error(
        "BOOK_VENUE_NAME=%r 未在 venues.py 中找到，请运行 "
        "`uv run python automations/venues.py` 查看可用列表",
        _venue_name,
    )
    sys.exit(1)
else:
    # 手动配置模式（BOOK_RESOURCE_ID 优先）
    VENUE_TYPE  = os.getenv("BOOK_VENUE_TYPE", "sports").strip().lower()
    RESOURCE_ID = int(os.getenv("BOOK_RESOURCE_ID", "0"))
    _sub_default: list[int] = []
    log_prefix  = "[manual]"

# 2. BOOK_SUB_IDS 可以覆盖字典中的子场地列表
SUB_IDS_RAW = os.getenv("BOOK_SUB_IDS", "").strip()
SUB_IDS: list[int] = (
    [int(x.strip()) for x in SUB_IDS_RAW.split(",") if x.strip()]
    if SUB_IDS_RAW else _sub_default
)

PREFER_TIMES_RAW = os.getenv("BOOK_PREFER_TIMES", "").strip()
DATE_OFFSET      = int(os.getenv("BOOK_DATE_OFFSET", "1"))
NUMBER           = int(os.getenv("BOOK_NUMBER", "1"))

# 脉冲模式配置
OPEN_TIME_STR  = os.getenv("BOOK_OPEN_TIME", "07:00").strip()   # 开放时刻 HH:MM
PULSE_BEFORE   = int(os.getenv("BOOK_PULSE_BEFORE", "60"))      # 开放前多少秒开始
PULSE_AFTER    = int(os.getenv("BOOK_PULSE_AFTER",  "60"))      # 开放后多少秒截止
PULSE_MAX      = int(os.getenv("BOOK_PULSE_MAX",    "10"))      # 最多发多少次

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
        raise RuntimeError(f"{target_date} 场馆 {RESOURCE_ID} 无空闲时段")

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
        raise RuntimeError(f"预约失败({reason}): {msg_}")

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
        raise RuntimeError(f"{target_date} 活动室 {RESOURCE_ID} 无空闲时段")

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
        raise RuntimeError(f"预约失败({reason}): {msg_}")

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

def _pulse_schedule(open_ts: float, before: float, after: float, n: int) -> list[float]:
    """
    生成 n 个绝对时间戳（秒），分布在 [open_ts - before, open_ts + after] 窗口内。

    分布策略：在窗口内取 n 个点，使间隔关于开放时刻呈"指数收缩"，
    即越靠近 open_ts 越密集，越远越稀疏。

    做法：将 [-before, +after] 映射到 [-1, 1]，用 sinh 的反函数（arcsinh）
    将均匀分布的 n 个点拉伸到中间密、两端稀的分布，再映射回时间轴。
    """
    import math
    window = before + after
    # 在 [0, 1] 上均匀取 n 个点
    unit = [i / (n - 1) for i in range(n)] if n > 1 else [0.5]
    # 映射到 [-before, +after]：先转到 [-1,1]，用 sinh 拉伸后再还原
    k = 3.0  # 拉伸系数，越大越集中在中心
    stretched = [math.sinh(k * (u * 2 - 1)) for u in unit]
    lo, hi = stretched[0], stretched[-1]
    # 归一化回 [-before, +after]
    offsets = [(s - lo) / (hi - lo) * window - before for s in stretched]
    return [open_ts + off for off in offsets]


def main() -> None:
    if RESOURCE_ID == 0:
        log.error("请在 .env 中配置 BOOK_RESOURCE_ID")
        sys.exit(1)

    target_date = datetime.date.today() + datetime.timedelta(days=DATE_OFFSET)
    runner = _run_sports if VENUE_TYPE == "sports" else _run_activity

    # 计算今天的开放时刻（Unix timestamp）
    hh, mm = map(int, OPEN_TIME_STR.split(":"))
    today = datetime.date.today()
    open_dt = datetime.datetime(today.year, today.month, today.day, hh, mm, 0)
    open_ts = open_dt.timestamp()

    schedule = _pulse_schedule(open_ts, PULSE_BEFORE, PULSE_AFTER, PULSE_MAX)
    now = time.time()

    log.info(
        "%s 脉冲预约模式: type=%s resource_id=%d date=%s open=%s "
        "window=[-%ds,+%ds] max=%d次",
        log_prefix, VENUE_TYPE, RESOURCE_ID, target_date, OPEN_TIME_STR,
        PULSE_BEFORE, PULSE_AFTER, PULSE_MAX,
    )
    log.info(
        "脉冲时刻: %s",
        [datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S") for t in schedule],
    )

    # 跳过已过期的时间点
    schedule = [t for t in schedule if t >= now]
    if not schedule:
        log.warning("所有脉冲时刻均已过期，立即执行一次")
        schedule = [now]

    for idx, fire_ts in enumerate(schedule, 1):
        wait = fire_ts - time.time()
        if wait > 0:
            log.info("等待 %.1f 秒后发起第 %d/%d 次请求 ...", wait, idx, len(schedule))
            time.sleep(wait)

        log.info("── 第 %d/%d 次尝试 ──", idx, len(schedule))
        try:
            runner(target_date)
            log.info("预约成功，退出脉冲循环")
            return                      # 成功即退出
        except Exception as e:
            msg = str(e)
            # "未到服务时间"：不报错，等下一个脉冲
            if "服务时间" in msg or "not_in_service_time" in msg:
                log.info("服务尚未开放: %s", msg)
            # "已有未结束预约"：说明已经抢到过，直接退出
            elif "未结束的预约" in msg or "existing_reservation" in msg:
                log.info("已存在预约，无需重复预约，退出")
                _notify("已存在有效预约，跳过本次自动预约")
                return
            else:
                log.error("第 %d 次失败: %s", idx, msg, exc_info=True)

    # 所有脉冲均未成功
    fail_msg = f"脉冲窗口内 {len(schedule)} 次尝试均未成功预约"
    log.error(fail_msg)
    _notify(fail_msg)
    sys.exit(1)


if __name__ == "__main__":
    main()
