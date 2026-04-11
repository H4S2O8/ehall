"""
debug_booking_751.py
测试 id=751（活动室）完整预约流程：
  Step1: 用 requests 调 launch_resource() 获取 process_url
  Step2: 用 Playwright fill_workflow_form() 在 workflow5 填表提交
"""
import asyncio
import os
import json
import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fudan_spider.apis.booking import (
    login_booking,
    make_storage_state,
    get_calendar,
    launch_resource,
    fill_workflow_form,
)

RESOURCE_ID      = 751
TARGET_SUB_ID    = 759           # 新光华悦动馆（台球室）
TARGET_TIME      = "20:00-22:00" # 想要的时段，没有则取第一个空闲
PHONE         = os.getenv("fudan_phone", "")
MAJOR         = os.getenv("fudan_major", "")
EMAIL         = os.getenv("fudan_email", "")
ACTIVITY      = os.getenv("fudan_activity_desc", "打台球")
APPLY_FILE    = os.getenv("fudan_application_file", "").strip("'\"") or None
STORAGE_FILE  = "booking_storage.json"


async def main():
    # ── 1. 登录 ──────────────────────────────────────────────────
    print("[1] 登录...")
    se = login_booking(None)
    make_storage_state(se, STORAGE_FILE)
    print(f"    storage_state: {STORAGE_FILE}")

    # ── 2. 查询明天空闲时段 ───────────────────────────────────────
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    print(f"\n[2] 查询 {tomorrow} 的空闲时段...")
    cal = get_calendar(se, RESOURCE_ID, tomorrow)

    time_slots    = cal["time_slots"]
    sub_resources = cal["sub_resources"]
    availability  = cal["availability"]
    date_str      = tomorrow.isoformat()

    print(f"    时段数={len(time_slots)}, 子场地数={len(sub_resources)}")
    for t in time_slots:
        print(f"      id={t['id']} {t['str_time']}")

    # 找目标时段的 period_id
    period_id = None
    for t in time_slots:
        if t["str_time"] == TARGET_TIME:
            period_id = t["id"]
            break
    if period_id is None and time_slots:
        # fallback: 第一个时段
        period_id = time_slots[0]["id"]
        print(f"    目标时段 {TARGET_TIME!r} 不存在，使用第一个: {time_slots[0]['str_time']}")

    # 找目标子场地（新光华悦动馆台球室），确认该时段空闲
    day_avail = availability.get(date_str, {})
    free_sub_id = None
    for sub in sub_resources:
        if sub["id"] != TARGET_SUB_ID:
            continue
        sid = str(sub["id"])
        slot = day_avail.get(sid, {}).get(str(period_id), {})
        if slot.get("status", 1) == 0:
            free_sub_id = sub["id"]
            print(f"    空闲子场地: id={sub['id']} {sub['name']}")
        else:
            print(f"    !! 目标场地 {sub['name']} 该时段不空闲 status={slot.get('status')}")
        break

    if free_sub_id is None:
        print("    !! 没有可预约的场地，退出")
        return

    # ── 3. Step1: launch ─────────────────────────────────────────
    print(f"\n[3] launch_resource(resource_id={free_sub_id}, period_id={period_id}, date={date_str})")
    result = launch_resource(se, free_sub_id, period_id, tomorrow)
    print(f"    结果: {result}")

    if not result.get("is_relate"):
        print("    is_relate=False，预约已直接完成（无需工作流）")
        return

    process_url = result["process_url"]
    print(f"    process_url: {process_url[:80]}...")

    # ── 4. Step2: 工作流填表 ─────────────────────────────────────
    print(f"\n[4] fill_workflow_form...")
    print(f"    major={MAJOR}, email={EMAIL}, phone={PHONE}")
    print(f"    activity={ACTIVITY}, file={APPLY_FILE}")
    await fill_workflow_form(
        process_url=process_url,
        storage_state=STORAGE_FILE,
        major=MAJOR,
        email=EMAIL,
        phone=PHONE,
        activity_desc=ACTIVITY,
        application_file=APPLY_FILE if APPLY_FILE and os.path.exists(APPLY_FILE) else None,
    )
    print("    [完成] 工作流表单提交成功")


if __name__ == "__main__":
    asyncio.run(main())
