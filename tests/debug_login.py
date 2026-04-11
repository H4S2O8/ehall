"""
调试新登录系统 id.fudan.edu.cn
抓取重定向链、页面结构、所需参数
"""
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os
import requests

se = requests.Session()
se.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
})

# 1. 访问 my.fudan.edu.cn，跟踪重定向链
print("=" * 60)
print("Step 1: 访问 my.fudan.edu.cn，观察重定向")
r = se.get("https://my.fudan.edu.cn/", allow_redirects=False)
print(f"  status: {r.status_code}")
print(f"  Location: {r.headers.get('Location', '无')}")

# 跟踪完整重定向链
r2 = se.get("https://my.fudan.edu.cn/", allow_redirects=True)
print(f"\n  最终 URL: {r2.url}")
print(f"  history: {[h.url for h in r2.history]}")

# 2. 直接访问新认证页
print("\n" + "=" * 60)
print("Step 2: 直接访问 id.fudan.edu.cn")
r3 = se.get("https://id.fudan.edu.cn/", allow_redirects=True)
print(f"  最终 URL: {r3.url}")
print(f"  status: {r3.status_code}")

# 3. 尝试带 service 参数访问（CAS 标准方式）
print("\n" + "=" * 60)
print("Step 3: 带 service 参数访问 id.fudan.edu.cn")
r4 = se.get(
    "https://id.fudan.edu.cn/idp/profile/cas/login",
    params={"service": "https://my.fudan.edu.cn/"},
    allow_redirects=False,
)
print(f"  status: {r4.status_code}")
print(f"  url: {r4.url}")
print(f"  Location: {r4.headers.get('Location', '无')}")
print(f"  body[:300]: {r4.text[:300]}")

# 4. 查看 cookies
print("\n" + "=" * 60)
print("当前 cookies:")
for c in se.cookies:
    print(f"  {c.domain:30} {c.name}={c.value[:4]}***")
