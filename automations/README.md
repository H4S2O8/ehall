# automations

存放定时/自动化脚本，独立于 MCP server 运行。

---

## auto_book.py — 自动预约场馆

在预约窗口开放时刻（默认 07:00）前后密集发起请求，越接近开放时刻越密集，抢到即退出。

### 配置（写入项目根目录的 `.env`）

#### 推荐：按名字选场馆

```bash
BOOK_VENUE_NAME=羽毛球-本部   # 从下方列表选填，脚本自动填充 ID
```

运行以下命令查看完整场馆列表：

```bash
uv run python automations/venues.py
```

输出示例：

```
别名                 类型        resource_id   说明
-----------------------------------------------------------------
羽毛球-本部          sports      1119          邯郸校区羽毛球馆
羽毛球-江湾          sports      1120          江湾校区羽毛球馆
乒乓球-本部          sports      1121          邯郸校区乒乓球室
台球室               activity    751           台球室（workflow5 审批）
...（更多见 automations/venues.py）
```

#### 全部配置项

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BOOK_VENUE_NAME` | 场馆名称（从 venues.py 列表中选填，自动推断 ID） | 空 |
| `BOOK_VENUE_TYPE` | 手动指定类型：`sports` 或 `activity`（覆盖字典） | `sports` |
| `BOOK_RESOURCE_ID` | 手动指定父场馆 ID（覆盖字典） | 空 |
| `BOOK_SUB_IDS` | 子场地 ID 列表，逗号分隔（留空则自动选） | 空 |
| `BOOK_PREFER_TIMES` | 期望时段，逗号分隔，如 `18:00-20:00,20:00-22:00` | 任意空闲 |
| `BOOK_DATE_OFFSET` | 预约哪天，相对今天的偏移天数 | `1`（明天） |
| `BOOK_NUMBER` | 预约人数 | `1` |
| `BOOK_OPEN_TIME` | 预约窗口开放时刻（`HH:MM`） | `07:00` |
| `BOOK_PULSE_BEFORE` | 开放前多少秒开始发请求 | `60` |
| `BOOK_PULSE_AFTER` | 开放后多少秒内继续发请求 | `60` |
| `BOOK_PULSE_MAX` | 脉冲窗口内最多发多少次请求（**成功即退出**） | `10` |

**脉冲分布说明**：请求时刻采用 sinh 拉伸分布，中间密集、两端稀疏。例如默认 10 次、前后各 60s：

```
-60s  -30s  -15s  -7s  -2s | +2s  +7s  +15s  +30s  +60s
 ←── 稀疏 ────────────────── 密集 ──────────────── 稀疏 ──→
                           ↑ 开放时刻
```

成功后立即退出，不再继续发请求。若服务尚未开放（返回"服务时间"错误）则静默等待下一个脉冲。

`activity` 模式还会读取 `fudan_major`、`fudan_email`、`fudan_phone`、`fudan_activity_desc`、`fudan_application_file`（均已在根目录 `.env.example` 中说明）。

### 如何更新场馆列表

`automations/venues.py` 维护已知场馆字典。若学校新增场馆或 ID 有变，可手动查询后更新：

```python
from dotenv import load_dotenv; load_dotenv()
from fudan_spider.apis.booking import login_booking, get_resource_list

se = login_booking()
for r in get_resource_list(se):
    print(r["id"], r["name"])
```

将查到的 ID 填入 `venues.py` 的 `VENUES` 字典即可。

### 手动运行

```bash
cd /path/to/ehall
uv run python automations/auto_book.py
```

### 定时运行（crontab）

脚本需在开放时刻前 `BOOK_PULSE_BEFORE` 秒之前启动。默认配置（前 60s）建议在 06:58 启动：

```crontab
# 06:58:30 启动，覆盖 [06:59:00, 07:01:00] 脉冲窗口
58 6 * * * sleep 30 && cd /path/to/ehall && uv run python automations/auto_book.py >> /tmp/auto_book.log 2>&1
```

### 定时运行（CodeBuddy Automation）

在 CodeBuddy 中创建 Automation，Prompt 填：

```
Run: uv run python automations/auto_book.py
Working directory: /path/to/ehall
```

Schedule: `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR=6;BYMINUTE=58`

> 注意：CodeBuddy Automation 不支持秒级精度，建议在脚本里适当调小 `BOOK_PULSE_BEFORE`（如 50s）以与启动时间匹配。

### 通知

设置 `BARK_URL` 后，预约成功/失败均会推送到手机。
