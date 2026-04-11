"""
共享登录 session。
所有调试脚本通过 `from tests._session import se` 获取已登录 session，
整个进程生命周期内只登录一次，不重复触发 MFA。
"""
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from fudan_spider.apis.booking import login_booking

print("[_session] 正在登录 booking.fudan.edu.cn ...")
se = login_booking(None)
print("[_session] 登录成功\n")
