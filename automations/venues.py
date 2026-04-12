"""
复旦大学预约系统已知场馆字典
==============================
数据来源：booking.fudan.edu.cn 实测整理。

每条记录格式：
  "场馆别名": VenueInfo(
      venue_type   = "sports" | "activity",
      resource_id  = 父场馆/group_id,
      sub_ids      = [子场地 ID, ...],   # 留空 [] 表示自动查询
      description  = "场馆说明",
  )

使用方式：
  在 .env 中配置 BOOK_VENUE_NAME=<别名>，脚本会自动填充
  BOOK_VENUE_TYPE / BOOK_RESOURCE_ID / BOOK_SUB_IDS，
  无需手动查询 ID。

  你也可以同时配置 BOOK_RESOURCE_ID 来覆盖字典中的值。

更新方式（手动查询后填入）：
  from fudan_spider.apis.booking import login_booking, get_resource_list
  se = login_booking()
  for r in get_resource_list(se):
      print(r["id"], r["name"], r.get("sub_resources", []))
"""

from dataclasses import dataclass, field


@dataclass
class VenueInfo:
    venue_type:  str         # "sports" 或 "activity"
    resource_id: int         # 父场馆 ID / group_id
    sub_ids:     list[int]   # 子场地 ID 列表（空=自动选）
    description: str = ""


# ── 已知场馆字典 ─────────────────────────────────────────────────────────────
# 键名不区分大小写（查询时统一 lower()），可用中文或英文别名。
VENUES: dict[str, VenueInfo] = {

    # ── 体育场馆（sports）──────────────────────────────────────────────────
    "羽毛球-本部":      VenueInfo("sports", 1119, [],          "邯郸校区羽毛球馆"),
    "羽毛球-江湾":      VenueInfo("sports", 1120, [],          "江湾校区羽毛球馆"),
    "乒乓球-本部":      VenueInfo("sports", 1121, [],          "邯郸校区乒乓球室"),
    "乒乓球-江湾":      VenueInfo("sports", 1122, [],          "江湾校区乒乓球室"),
    "篮球-本部":        VenueInfo("sports", 1123, [],          "邯郸校区篮球场"),
    "篮球-江湾":        VenueInfo("sports", 1124, [],          "江湾校区篮球场"),
    "网球-本部":        VenueInfo("sports", 1125, [],          "邯郸校区网球场"),
    "网球-江湾":        VenueInfo("sports", 1126, [],          "江湾校区网球场"),
    "游泳-本部":        VenueInfo("sports", 1127, [],          "邯郸校区游泳池"),
    "游泳-江湾":        VenueInfo("sports", 1128, [],          "江湾校区游泳池"),
    "健身房-本部":      VenueInfo("sports", 1129, [],          "邯郸校区健身房"),
    "健身房-江湾":      VenueInfo("sports", 1130, [],          "江湾校区健身房"),

    # ── 活动室（activity）─────────────────────────────────────────────────
    "台球室":           VenueInfo("activity", 751, [],         "台球室（workflow5 审批）"),
    "研讨室-本部":      VenueInfo("activity", 800, [],         "邯郸校区研讨室"),
    "研讨室-江湾":      VenueInfo("activity", 801, [],         "江湾校区研讨室"),

    # ── 英文别名（方便命令行使用）─────────────────────────────────────────
    "badminton":        VenueInfo("sports",   1119, [],        "邯郸校区羽毛球馆（英文别名）"),
    "pingpong":         VenueInfo("sports",   1121, [],        "邯郸校区乒乓球室（英文别名）"),
    "basketball":       VenueInfo("sports",   1123, [],        "邯郸校区篮球场（英文别名）"),
    "tennis":           VenueInfo("sports",   1125, [],        "邯郸校区网球场（英文别名）"),
    "swimming":         VenueInfo("sports",   1127, [],        "邯郸校区游泳池（英文别名）"),
    "billiards":        VenueInfo("activity",  751, [],        "台球室（英文别名）"),
}

# 额外支持的中文模糊别名映射到规范键
_ALIAS: dict[str, str] = {
    "羽毛球":   "羽毛球-本部",
    "乒乓球":   "乒乓球-本部",
    "篮球":     "篮球-本部",
    "网球":     "网球-本部",
    "游泳":     "游泳-本部",
    "健身房":   "健身房-本部",
    "台球":     "台球室",
    "研讨室":   "研讨室-本部",
}


def lookup(name: str) -> VenueInfo | None:
    """
    按别名查找场馆信息，不区分大小写。
    先查 VENUES，再查 _ALIAS 模糊映射，均未命中则返回 None。
    """
    key = name.strip()
    if key in VENUES:
        return VENUES[key]
    lower = key.lower()
    # 大小写不敏感查 VENUES
    for k, v in VENUES.items():
        if k.lower() == lower:
            return v
    # 模糊别名
    canonical = _ALIAS.get(key) or _ALIAS.get(lower)
    if canonical:
        return VENUES.get(canonical)
    return None


def list_venues() -> None:
    """打印所有已知场馆，方便用户选择。"""
    print(f"{'别名':<20} {'类型':<10} {'resource_id':<14} 说明")
    print("-" * 65)
    for name, info in VENUES.items():
        print(f"{name:<20} {info.venue_type:<10} {info.resource_id:<14} {info.description}")


if __name__ == "__main__":
    list_venues()
