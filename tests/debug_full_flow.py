"""
debug_full_flow.py
完整流程测试：登录 → 查询空闲 → 预约 → 填写工作流 → 取消预约
"""
import asyncio
import os
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
    cancel_reserve,
)

RESOURCE_ID   = 751
TARGET_SUB_ID = 759           # 新光华悦动馆（台球室）
TARGET_TIME   = "20:00-22:00"
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

    # 找目标时段
    period_id = None
    for t in time_slots:
        if t["str_time"] == TARGET_TIME:
            period_id = t["id"]
            break
    if period_id is None and time_slots:
        period_id = time_slots[0]["id"]
        print(f"    目标时段 {TARGET_TIME!r} 不存在，使用: {time_slots[0]['str_time']}")
    print(f"    period_id={period_id}")

    # 确认目标子场地空闲
    day_avail = availability.get(date_str, {})
    free_sub_id = None
    for sub in sub_resources:
        if sub["id"] != TARGET_SUB_ID:
            continue
        slot = day_avail.get(str(sub["id"]), {}).get(str(period_id), {})
        if slot.get("status", 1) == 0:
            free_sub_id = sub["id"]
            print(f"    空闲: id={sub['id']} {sub['name']}")
        else:
            print(f"    !! 目标场地 {sub['name']} 不空闲 status={slot.get('status')}")
        break

    if free_sub_id is None:
        print("    !! 没有可预约的场地，退出")
        return

    # ── 3. 预约 ──────────────────────────────────────────────────
    print(f"\n[3] launch_resource(resource_id={free_sub_id}, period_id={period_id}, date={date_str})")
    result = launch_resource(se, free_sub_id, period_id, tomorrow)
    print(f"    结果: {result}")

    if not result.get("is_relate"):
        print("    is_relate=False，预约直接完成（无需工作流）")
    else:
        process_url = result["process_url"]
        print(f"    process_url: {process_url[:80]}...")

        # ── 4. 填写工作流表单 ─────────────────────────────────────
        print(f"\n[4] fill_workflow_form...")
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

    # ── 5. 取消预约 ──────────────────────────────────────────────
    print(f"\n[5] cancel_reserve...")
    await cancel_reserve(STORAGE_FILE)
    print("    [完成] 取消预约成功")


if __name__ == "__main__":
    asyncio.run(main())
