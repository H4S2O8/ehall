"""
一卡通 API
- 余额查询
- TODO: 消费记录
"""

from curl_cffi.requests import Session


def get_card_info(se: Session) -> dict:
    """查询一卡通基本信息与余额"""
    resp = se.post("https://my.fudan.edu.cn/data_tables/ykt_xx.json")
    resp.raise_for_status()
    return resp.json()
