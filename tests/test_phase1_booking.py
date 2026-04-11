"""
Phase 1 测试：体育场馆预约查询
https://booking.fudan.edu.cn/reservation/fe/site/special/special?id=48

运行:
    uv run python -m tests.test_phase1_booking
"""
import sys
import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fudan_spider.apis.booking import (
    login_booking,
    get_topic_detail,
    get_resource_list,
    get_schedule,
    get_available_slots,
)


def main():
    print("=" * 55)
    print("Phase 1 Test: 体育场馆预约查询")
    print("=" * 55)

    # ── 登录 ──────────────────────────────────────────────
    print("\n[INFO] 登录 booking.fudan.edu.cn ...")
    try:
        se = login_booking(None)
    except Exception as e:
        print(f"[FAIL] 登录失败: {e}")
        sys.exit(1)
    print("[PASS] 登录成功")

    # ── 专题详情 ──────────────────────────────────────────
    print("\n─── 专题详情（id=48）───")
    detail = get_topic_detail(se)
    print(f"  名称:     {detail['name']}")
    print(f"  总访问数: {detail['visit_num']:,}")
    print(f"  总预约数: {detail['appointment_num']:,}")

    # ── 场馆列表 ──────────────────────────────────────────
    print("\n─── 场馆列表 ───")
    resources = get_resource_list(se)
    print(f"  共 {len(resources)} 个场馆：")
    for res in resources:
        print(f"    [{res['id']}] {res['name']}")

    # ── 时段查询（取第一个场馆） ──────────────────────────
    target = resources[0]
    today  = datetime.date.today().isoformat()
    print(f"\n─── 时段占用（{target['name']} | {today}）───")
    try:
        schedule = get_schedule(se, target["id"], today)
    except Exception as e:
        print(f"[ERROR] 时段查询失败: {e}")
        sys.exit(1)

    sub_resources = schedule["sub_resources"]
    time_slots    = schedule["time_slots"]
    availability  = schedule["availability"]

    print(f"  时段数: {len(time_slots)}，子场地数: {len(sub_resources)}")
    print()

    # 表头
    sub_names = [r["name"] for r in sub_resources]
    col_w = 12
    header = f"  {'时段':<14}" + "".join(f"{n:<{col_w}}" for n in sub_names)
    print(header)
    print("  " + "─" * (14 + col_w * len(sub_names)))

    for slot in time_slots:
        row = f"  {slot['str_time']:<14}"
        for sub in sub_resources:
            rid = str(sub["id"])
            tid = str(slot["id"])
            cell = availability.get(rid, {}).get(tid, {})
            if cell.get("occupy"):
                status = "■ 占用"
            else:
                status = "□ 空闲"
            row += f"{status:<{col_w}}"
        print(row)

    # ── 空闲时段汇总 ──────────────────────────────────────
    print(f"\n─── 空闲时段（{target['name']} | {today}）───")
    available = get_available_slots(se, target["id"], today)
    if available:
        for a in available:
            print(f"  [{a['sub_resource_name']}] {a['str_time']}")
    else:
        print("  今日已无空闲时段")

    print("\n" + "=" * 55)
    print("[PASS] Phase 1 体育场馆预约查询全部通过！")
    print("=" * 55)


if __name__ == "__main__":
    main()
