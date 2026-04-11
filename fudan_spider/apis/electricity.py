"""
宿舍用电 API
- 近期用电记录
- TODO: 余额预警
"""

from requests import Session


def get_electricity(se: Session, length: int = 20) -> dict:
    """查询近期宿舍用电记录"""
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
        "start": "0",
        "length": str(length),
        "search[value]": "",
        "search[regex]": "false",
    }
    resp = se.post(
        "https://my.fudan.edu.cn/data_tables/ykt_xszsqyydqk.json",
        data=payload,
    )
    resp.raise_for_status()
    return resp.json()
