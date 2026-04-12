"""
复旦大学预约系统已知场馆字典
==============================
数据来源：booking.fudan.edu.cn topic/resource-list?id=48&pageSize=200 实测整理。

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

  运行 `uv run python automations/venues.py` 查看完整列表。
  你也可以同时配置 BOOK_RESOURCE_ID 来覆盖字典中的值。

更新方式（手动查询后填入）：
  from fudan_spider.apis.booking import login_booking, get_resource_list
  se = login_booking()
  for r in get_resource_list(se):
      print(r["id"], r["name"])
"""

from dataclasses import dataclass, field


@dataclass
class VenueInfo:
    venue_type:  str         # "sports" 或 "activity"
    resource_id: int         # 父场馆 ID / group_id
    sub_ids:     list[int]   # 子场地 ID 列表（空=自动选）
    description: str = ""


# ── 已知场馆字典 ─────────────────────────────────────────────────────────────
# 键名即 BOOK_VENUE_NAME 可填写的值，查询时不区分大小写。
VENUES: dict[str, VenueInfo] = {

    # ── 邯郸（本部）北区体育馆 ─────────────────────────────────────────────
    "北区体育馆-羽毛球":       VenueInfo("sports",  938,  [], "邯郸校区北区体育馆"),
    "北区体育馆-篮球":         VenueInfo("sports",  925,  [], "邯郸校区北区体育馆"),
    "北区体育馆-排球":         VenueInfo("sports",  964,  [], "邯郸校区北区体育馆"),
    "北区体育馆-乒乓球":       VenueInfo("sports",  977,  [], "邯郸校区北区体育馆"),
    "北区体育馆-舞蹈房":       VenueInfo("sports",  990,  [], "邯郸校区北区体育馆"),

    # ── 邯郸（本部）正大体育馆 ────────────────────────────────────────────
    "正大体育馆-羽毛球":       VenueInfo("sports",  951,  [], "邯郸校区正大体育馆"),

    # ── 邯郸（本部）室外 ──────────────────────────────────────────────────
    "本北高速室外网球场-网球":  VenueInfo("sports", 1349, [], "邯郸校区本北高速旁室外网球场"),
    "南区网球场-网球":         VenueInfo("sports", 1003, [], "邯郸校区南区网球场"),
    "南区乒乓房-乒乓球":       VenueInfo("sports", 1016, [], "邯郸校区南区乒乓球室"),
    "国权路运动场-网球":       VenueInfo("sports", 1042, [], "邯郸校区国权路运动场"),
    "国福路田径场-足球场":     VenueInfo("sports", 1029, [], "邯郸校区国福路田径场"),

    # ── 江湾校区 ──────────────────────────────────────────────────────────
    "江湾综合体育馆-羽毛球":   VenueInfo("sports", 1055, [], "江湾校区综合体育馆"),
    "江湾综合体育馆-篮球":     VenueInfo("sports", 1087, [], "江湾校区综合体育馆"),
    "江湾综合体育馆-排球":     VenueInfo("sports", 1103, [], "江湾校区综合体育馆"),
    "江湾综合体育馆-乒乓球":   VenueInfo("sports", 1119, list(range(1120, 1132)), "江湾校区综合体育馆（12张台）"),
    "江湾综合体育馆-网球":     VenueInfo("sports", 1071, [], "江湾校区综合体育馆"),
    "江湾综合体育馆-舞蹈房":   VenueInfo("sports", 1293, [], "江湾校区综合体育馆"),
    "江湾室外体育场-网球":     VenueInfo("sports", 1135, [], "江湾校区室外体育场"),
    "江湾室外体育场-足球场":   VenueInfo("sports", 1309, [], "江湾校区室外体育场"),

    # ── 枫林校区 ──────────────────────────────────────────────────────────
    "枫林综合体育馆-篮球":     VenueInfo("sports", 1153, [], "枫林校区综合体育馆"),
    "枫林学生活动中心-羽毛球": VenueInfo("sports", 1169, [], "枫林校区学生活动中心"),
    "枫林学生活动中心-乒乓球": VenueInfo("sports", 1185, [], "枫林校区学生活动中心"),

    # ── 张江校区 ──────────────────────────────────────────────────────────
    "张江学生活动中心-羽毛球": VenueInfo("sports", 1201, [], "张江校区学生活动中心"),
    "张江学生活动中心-网球":   VenueInfo("sports", 1217, [], "张江校区学生活动中心"),
    "张江学生活动中心-乒乓球": VenueInfo("sports", 1233, [], "张江校区学生活动中心"),

}

# 中文模糊别名 → 规范键（当用户只填"羽毛球"时默认到邯郸北区）
_ALIAS: dict[str, str] = {
    "羽毛球":   "北区体育馆-羽毛球",
    "乒乓球":   "北区体育馆-乒乓球",
    "篮球":     "北区体育馆-篮球",
    "排球":     "北区体育馆-排球",
    "舞蹈房":   "北区体育馆-舞蹈房",
    "网球":     "南区网球场-网球",
    "足球":     "江湾室外体育场-足球场",
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
    for k, v in VENUES.items():
        if k.lower() == lower:
            return v
    canonical = _ALIAS.get(key) or _ALIAS.get(lower)
    if canonical:
        return VENUES.get(canonical)
    return None


def list_venues() -> None:
    """打印所有已知场馆，方便用户选择。"""
    print(f"{'别名':<24} {'类型':<10} {'resource_id':<14} 说明")
    print("-" * 70)
    for name, info in VENUES.items():
        print(f"{name:<24} {info.venue_type:<10} {info.resource_id:<14} {info.description}")


if __name__ == "__main__":
    list_venues()
