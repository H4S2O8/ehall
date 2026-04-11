"""
Phase 1 测试：跑通 UIS 统一身份认证登录（id.fudan.edu.cn）
"""
import sys
import os

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
        print("[SKIP] 未检测到账号密码环境变量，请配置 .env 后重试。")
        sys.exit(0)

    otp_secret = os.getenv("fudan_otp_secret", "")
    print(f"[INFO] 账号: {username[:3]}***")
    print(f"[INFO] TOTP: {'已配置' if otp_secret else '未配置（若账号开启 MFA 将失败）'}")
    print("[INFO] 正在登录 id.fudan.edu.cn ...")

    try:
        se = login()
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        sys.exit(1)

    print("[PASS] 登录成功，Session 已建立")
    print(f"[INFO] cookies: {list(se.cookies.keys())}")

    # 验证：访问 my.fudan.edu.cn
    print("[INFO] 验证 Session 可访问 my.fudan.edu.cn ...")
    resp = se.get("https://my.fudan.edu.cn/")
    print(f"[INFO] 最终 URL: {resp.url}")
    if "id.fudan.edu.cn" in resp.url:
        print("[FAIL] 仍被重定向到登录页，Session 未生效")
        sys.exit(1)

    print(f"[PASS] my.fudan.edu.cn 访问成功，状态码: {resp.status_code}")
    print("=" * 50)
    print("Phase 1 登录测试通过！")
    print("=" * 50)
    return se


if __name__ == "__main__":
    test_login()
