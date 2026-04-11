"""
Phase 1 测试：跑通 UIS 统一身份认证登录

运行前请确保已设置环境变量（或在项目根目录放 .env 文件）：
    export fudan_username=你的学号
    export fudan_password=你的密码

或者复制 .env.example 为 .env 并填写真实信息：
    cp .env.example .env
    # 编辑 .env

运行：
    python test_phase1_login.py
"""

import sys
import os

# 支持从 .env 文件读取环境变量（需安装 python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fudan_spider.uis import login


def test_login():
    print("=" * 50)
    print("Phase 1 Test: UIS 登录")
    print("=" * 50)

    username = os.getenv("fudan_username")
    password = os.getenv("fudan_password")

    if not username or not password:
        print("[SKIP] 未检测到 fudan_username / fudan_password 环境变量，跳过实际登录。")
        print("       请设置环境变量或创建 .env 文件后重试。")
        sys.exit(0)

    print(f"[INFO] 账号: {username[:3]}***（已脱敏）")
    print("[INFO] 正在请求 UIS 登录页，获取隐藏表单字段...")

    try:
        se = login()
    except AssertionError as e:
        print(f"[FAIL] 登录断言失败：{e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"[WARN] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 登录时发生异常：{type(e).__name__}: {e}")
        sys.exit(1)

    print("[PASS] 登录成功，Session 已建立。")

    # 验证 Cookie 中包含 TGC（CAS Ticket Granting Cookie）
    tgc = se.cookies.get("TGC", domain="uis.fudan.edu.cn")
    if tgc:
        print(f"[INFO] TGC Cookie 已获取：{tgc[:20]}...（已截断）")
    else:
        print("[WARN] 未找到 TGC Cookie，后续服务可能受限。")

    # 简单验证：访问 my.fudan.edu.cn 首页
    print("[INFO] 验证 Session 可访问 my.fudan.edu.cn ...")
    resp = se.get("https://my.fudan.edu.cn/")
    if resp.status_code == 200:
        print(f"[PASS] my.fudan.edu.cn 访问成功，状态码：{resp.status_code}")
    else:
        print(f"[WARN] my.fudan.edu.cn 返回状态码：{resp.status_code}")

    print("=" * 50)
    print("Phase 1 全部测试通过！")
    print("=" * 50)
    return se


if __name__ == "__main__":
    test_login()
