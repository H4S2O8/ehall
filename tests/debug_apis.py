"""临时调试：打印各接口原始响应"""
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fudan_spider.uis import login

se = login()
print("[PASS] 登录成功")
print(f"  cookies: {dict(se.cookies)}\n")

# 访问 my.fudan.edu.cn 首页，看是否需要二次跳转
r = se.get("https://my.fudan.edu.cn/")
print(f"my.fudan.edu.cn GET -> {r.status_code} | url: {r.url}")

# 一卡通
r1 = se.post("https://my.fudan.edu.cn/data_tables/ykt_xx.json")
print(f"\n[card] status: {r1.status_code} | url: {r1.url}")
print(f"[card] body: {repr(r1.text[:500])}")

# 用电
payload = {
    "draw": "1",
    "columns[0][data]": "0", "columns[0][name]": "",
    "columns[0][searchable]": "true", "columns[0][orderable]": "false",
    "columns[0][search][value]": "", "columns[0][search][regex]": "false",
    "columns[1][data]": "1", "columns[1][name]": "",
    "columns[1][searchable]": "true", "columns[1][orderable]": "false",
    "columns[1][search][value]": "", "columns[1][search][regex]": "false",
    "columns[2][data]": "2", "columns[2][name]": "",
    "columns[2][searchable]": "true", "columns[2][orderable]": "false",
    "columns[2][search][value]": "", "columns[2][search][regex]": "false",
    "start": "0", "length": "7",
    "search[value]": "", "search[regex]": "false",
}
r2 = se.post("https://my.fudan.edu.cn/data_tables/ykt_xszsqyydqk.json", data=payload)
print(f"\n[elec] status: {r2.status_code} | url: {r2.url}")
print(f"[elec] body: {repr(r2.text[:500])}")
