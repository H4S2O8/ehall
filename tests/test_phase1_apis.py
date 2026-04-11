"""
Phase 1 测试：一卡通余额 & 宿舍用电

依赖已登录的 Session，运行前需配置 .env：
    fudan_username=xxx
    fudan_password=xxx

运行：
    python -m tests.test_phase1_apis
"""

import sys
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fudan_spider.uis import login
from fudan_spider.apis.card import get_card_info
from fudan_spider.apis.electricity import get_electricity


def _section(title: str):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def test_card(se):
    _section("一卡通信息")
    try:
        data = get_card_info(se)
    except Exception as e:
        print(f"[ERROR] 请求失败：{type(e).__name__}: {e}")
        return False

    rows = data.get("data", [])
    if not rows:
        print("[WARN] 返回数据为空，可能账号无一卡通绑定")
        return True

    row = rows[0]
    # data 格式: [学号, 姓名, 状态, 校区, 有效期, 余额]
    fields = ["学号", "姓名", "状态", "可用校区", "有效期", "余额(元)"]
    for k, v in zip(fields, row):
        # 学号、姓名脱敏
        if k == "学号":
            display = f"{str(v)[:3]}***"
        elif k == "姓名":
            s = str(v)
            display = s[0] + "*" * (len(s) - 1) if len(s) > 0 else v
        else:
            display = v
        print(f"  {k}: {display}")

    print("[PASS] 一卡通查询成功")
    return True


def test_electricity(se):
    _section("宿舍用电记录")
    try:
        data = get_electricity(se, length=7)
    except Exception as e:
        print(f"[ERROR] 请求失败：{type(e).__name__}: {e}")
        return False

    rows = data.get("data", [])
    total = data.get("recordsTotal", 0)

    if not rows:
        print("[WARN] 暂无用电记录（可能未绑定宿舍）")
        return True

    print(f"  共 {total} 条记录，显示最近 {len(rows)} 条：\n")
    print(f"  {'日期':<14} {'宿舍':<30} {'用电(度)'}")
    print(f"  {'─'*12} {'─'*30} {'─'*8}")
    for date, room, kwh in rows:
        print(f"  {date:<14} {room:<30} {kwh}")

    print("\n[PASS] 用电记录查询成功")
    return True


def main():
    print("=" * 50)
    print("Phase 1 Test: APIs（一卡通 & 用电）")
    print("=" * 50)

    print("\n[INFO] 登录中...")
    try:
        se = login()
    except Exception as e:
        print(f"[FAIL] 登录失败：{e}")
        sys.exit(1)
    print("[PASS] 登录成功")

    results = [
        test_card(se),
        test_electricity(se),
    ]

    print(f"\n{'=' * 50}")
    if all(results):
        print("Phase 1 API 测试全部通过！")
    else:
        print("部分测试未通过，请检查上方输出。")
    print("=" * 50)

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
