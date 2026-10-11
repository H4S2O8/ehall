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

  # ── 开放时刻抢占（单发 + 换 session）────────────────────────────────
  # 实测（2026-09）：开放前后密集连发会触发「点击太频繁」→「前方拥挤」，
  # 该 session 之后每次提交都被拒；重新登录换 session 立即恢复。
  # 因此策略是：开放前登录好，开放后 0.3s 发第一枪，失败隔 BOOK_RETRY_GAP
  # 秒再发，遇到限流立刻换 session，直到 BOOK_DEADLINE_MIN 分钟截止。
  BOOK_OPEN_TIME       预约窗口开放的时刻，格式 "HH:MM"（默认 "07:00"）
  BOOK_LOGIN_LEAD      开放前多少秒登录（默认 60）
  BOOK_RETRY_GAP       两次提交之间的最小间隔秒数（默认 1.5，不要小于 1）
  BOOK_DEADLINE_MIN    开放后最多坚持多少分钟（默认 10）

  # ── activity 模式额外需要（也可直接读 fudan_* 变量）─────────────────
  # fudan_major / fudan_email / fudan_phone / fudan_activity_desc
  # fudan_application_file（可选）

运行方式：
  uv run python automations/auto_book.py

在 BOOK_OPEN_TIME 前 1~2 分钟启动即可，脚本自己等到时刻：
  crontab: 58 6 * * * cd /path/to/ehall && uv run python automations/auto_book.py
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

# 开放时刻抢占配置
OPEN_TIME_STR  = os.getenv("BOOK_OPEN_TIME", "07:00").strip()
LOGIN_LEAD     = int(os.getenv("BOOK_LOGIN_LEAD", "60"))
RETRY_GAP      = max(1.0, float(os.getenv("BOOK_RETRY_GAP", "1.5")))
DEADLINE_MIN   = int(os.getenv("BOOK_DEADLINE_MIN", "10"))

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

def _server_offset(se) -> float:
    """server_time - local_time（秒），用响应头 Date 校准，失败返回 0。"""
    import email.utils
    from fudan_spider.apis.booking import BOOKING_BASE
    try:
        t0 = time.time()
        r = se.get(f"{BOOKING_BASE}/reservation/api/topic/detail",
                   params={"id": 48}, timeout=8)
        t1 = time.time()
        srv = email.utils.parsedate_to_datetime(r.headers["Date"]).timestamp()
        return srv - (t0 + t1) / 2
    except Exception as e:  # noqa: BLE001
        log.warning("时钟校准失败，按本地时间: %s", e)
        return 0.0


def _sleep_until(ts: float, offset: float) -> None:
    while True:
        remain = ts - (time.time() + offset)
        if remain <= 0:
            return
        time.sleep(min(remain, 30))


def _login_retry(tag: str = ""):
    from fudan_spider.apis.booking import login_booking
    from fudan_spider.apis.waf_browser import prepare
    for i in range(1, 6):
        try:
            se = login_booking()
            # 预约 POST 要经浏览器页面发出（瑞数动态后缀），提前启动免得开放时现等
            prepare(se)
            log.info("登录成功%s（第 %d 次）", tag, i)
            return se
        except Exception as e:  # noqa: BLE001
            log.warning("登录失败%s（第 %d 次）: %s", tag, i, e)
            time.sleep(2)
    raise RuntimeError("登录连续 5 次失败")


def _sports_targets(se, target_date: datetime.date) -> list[tuple[str, list[int], int]]:
    """
    生成候选列表 [(时段文本, 子场地 id 列表, period_id)]，按优先级排列。

    - 有 PREFER_TIMES：按其顺序取对应 period_id（不存在的时段跳过并告警）。
    - 无 PREFER_TIMES：取当前仍有空位的所有时段，按时间顺序。
    - 子场地：BOOK_SUB_IDS 非空则用之，否则传全部子场地让服务端分配。
    """
    from fudan_spider.apis.booking import get_schedule

    sched = get_schedule(se, RESOURCE_ID, target_date)
    time_map = {t["str_time"]: t["id"] for t in sched["time_slots"]}
    sub_ids = SUB_IDS or [r["id"] for r in sched["sub_resources"]]

    if PREFER_TIMES:
        targets = []
        for p in PREFER_TIMES:
            if p in time_map:
                targets.append((p, sub_ids, time_map[p]))
            else:
                log.warning("偏好时段 %s 不在该场馆时段表中，跳过", p)
        return targets

    free_times: list[str] = []
    for t in sched["time_slots"]:
        tid = str(t["id"])
        if any(not cells.get(tid, {}).get("occupy", True)
               for cells in sched["availability"].values()):
            free_times.append(t["str_time"])
    return [(t, sub_ids, time_map[t]) for t in free_times]


def _sports_attempt(se, target_date: datetime.date, label: str,
                    sub_ids: list[int], period_id: int) -> str:
    """提交一次预约。返回 ok / closed / gone / throttled / existing / error。"""
    from fudan_spider.apis.booking import book_resource

    try:
        r = book_resource(se, group_id=RESOURCE_ID, sub_resource_ids=sub_ids,
                          period_id=period_id, date=target_date,
                          phone=os.getenv("fudan_phone", ""))
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "拥挤" in msg or "频繁" in msg:
            log.info("  %s: 限流（%s）", label, msg[-20:])
            return "throttled"
        if "容量不足" in msg or "已被" in msg:
            log.info("  %s: 没了（%s）", label, msg[-30:])
            return "gone"
        if "不可预约" in msg:
            # 日期尚在可约范围外 / 窗口未切换时也是这句，不能当"没了"
            log.info("  %s: 未开放（%s）", label, msg[-32:])
            return "closed"
        log.error("  %s: 异常 %s", label, msg[:120])
        return "error"

    if r.get("ok"):
        log.info("  %s: 成功 %s", label, r)
        return "ok"
    reason = r.get("reason")
    if reason == "not_in_service_time":
        log.info("  %s: 未开放", label)
        return "closed"
    if reason == "existing_reservation":
        log.info("  %s: 系统拒绝，已有未结束预约: %s", label, r.get("message"))
        return "existing"
    log.error("  %s: 失败 %s", label, r)
    return "error"


def _run_sports(target_date: datetime.date) -> None:
    """
    开放时刻抢占：
      open-LOGIN_LEAD 登录 + 校准时钟 + 生成候选
      open+0.3s 起单发；失败隔 RETRY_GAP；限流则换 session；
      开放 3 秒内死守第一优先级，之后轮换候选；DEADLINE_MIN 分钟后放弃。
    """
    if RESOURCE_ID == 0:
        raise ValueError("BOOK_RESOURCE_ID 未配置")

    hh, mm = map(int, OPEN_TIME_STR.split(":"))
    today = datetime.date.today()
    open_ts = datetime.datetime(today.year, today.month, today.day, hh, mm).timestamp()
    first_shot = open_ts + 0.3
    rotate_after = open_ts + 3.0
    deadline = open_ts + DEADLINE_MIN * 60

    if time.time() < open_ts - LOGIN_LEAD:
        log.info("等待到开放前 %ds 再登录 ...", LOGIN_LEAD)
        _sleep_until(open_ts - LOGIN_LEAD, 0.0)

    se = _login_retry()
    off = _server_offset(se)
    log.info("服务器时钟偏移 %+.3fs", off)
    targets = _sports_targets(se, target_date)
    if not targets:
        raise RuntimeError(f"{target_date} 场馆 {RESOURCE_ID} 没有可用候选时段")
    log.info("候选顺序: %s", [t[0] for t in targets])
    _sleep_until(first_shot, off)

    alive = list(targets)
    idx = 0
    n_req = 0
    while alive and time.time() + off < deadline:
        label, sub_ids, pid = alive[idx % len(alive)]
        n_req += 1
        res = _sports_attempt(se, target_date, label, sub_ids, pid)
        if res == "ok":
            msg = f"预约成功: {target_date} {label}"
            log.info(msg)
            _notify(msg)
            return
        if res == "existing":
            _notify("已存在未结束预约，系统拒绝本次自动预约")
            return
        if res == "gone":
            alive.remove((label, sub_ids, pid))
            continue                        # 立刻试下一个候选
        if res == "throttled":
            time.sleep(2.0)
            se = _login_retry("（换 session）")
            continue                        # 新 session 从同一候选重试
        if res == "error" or time.time() + off > rotate_after:
            idx += 1
        time.sleep(RETRY_GAP)

    raise RuntimeError(
        f"{target_date} 未预约成功：{n_req} 次提交，剩余候选 {[a[0] for a in alive]}"
    )


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

def _run_activity_loop(target_date: datetime.date) -> None:
    """活动室：开放后每 RETRY_GAP 秒试一次，直到成功或 DEADLINE_MIN 分钟。"""
    hh, mm = map(int, OPEN_TIME_STR.split(":"))
    today = datetime.date.today()
    open_ts = datetime.datetime(today.year, today.month, today.day, hh, mm).timestamp()
    deadline = open_ts + DEADLINE_MIN * 60
    _sleep_until(open_ts + 0.3, 0.0)

    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            _run_activity(target_date)
            return
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "未结束的预约" in msg or "existing_reservation" in msg:
                _notify("已存在未结束预约，系统拒绝本次自动预约")
                return
            if "容量不足" in msg:
                raise RuntimeError(f"{target_date} 活动室已被抢光") from e
            log.info("第 %d 次未成功: %s", attempt, msg[:80])
        time.sleep(max(RETRY_GAP, 5.0))
    raise RuntimeError(f"{target_date} 活动室 {attempt} 次尝试均未成功")


def main() -> None:
    if RESOURCE_ID == 0:
        log.error("请在 .env 中配置 BOOK_RESOURCE_ID 或 BOOK_VENUE_NAME")
        sys.exit(1)

    target_date = datetime.date.today() + datetime.timedelta(days=DATE_OFFSET)
    log.info(
        "%s 开始: type=%s resource_id=%d date=%s open=%s gap=%.1fs deadline=%dmin",
        log_prefix, VENUE_TYPE, RESOURCE_ID, target_date, OPEN_TIME_STR,
        RETRY_GAP, DEADLINE_MIN,
    )
    try:
        if VENUE_TYPE == "sports":
            _run_sports(target_date)
        else:
            _run_activity_loop(target_date)
    except RuntimeError as e:
        log.error("%s", e)
        _notify(str(e)[:200])
        sys.exit(1)


def _self_remove_from_crontab() -> None:
    """从 crontab 中删除含当前场馆名的一次性任务（由 schedule_book 写入）。

    在 Python 进程里执行，LANG 正常，中文匹配可靠。
    只在 BOOK_VENUE_NAME 环境变量存在时生效。
    """
    import subprocess, hashlib, tempfile

    venue = os.getenv("BOOK_VENUE_NAME", "").strip()
    if not venue:
        return

    tag = f"ehall-{hashlib.md5(venue.encode()).hexdigest()[:8]}"
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return

    lines = result.stdout.splitlines()
    new_lines = [l for l in lines if tag not in l]
    if len(new_lines) == len(lines):
        return  # 没找到，不需要操作

    if new_lines:
        new_crontab = "\n".join(new_lines) + "\n"
        with tempfile.NamedTemporaryFile("w", suffix=".cron", delete=False) as f:
            f.write(new_crontab)
            tmp = f.name
        subprocess.run(["crontab", tmp], check=True)
        os.unlink(tmp)
    else:
        subprocess.run(["crontab", "-r"], check=True)

    log.info("已从 crontab 删除一次性任务（tag=%s）", tag)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 — 任何未预期崩溃都要通知到手机
        log.exception("auto_book 异常退出")
        _notify(f"自动预约脚本崩溃: {type(e).__name__}: {e}"[:200])
        raise
    finally:
        _self_remove_from_crontab()
