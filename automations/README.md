# automations

存放定时/自动化脚本，独立于 MCP server 运行。

---

## auto_book.py — 自动预约场馆

在预约窗口开放时刻（默认 07:00）准点提交，失败按固定间隔重试，遇到限流立刻换 session，抢到即退出。

> **为什么不密集连发**：实测开放前后几秒内连发 3~4 次就会触发「点击太频繁了」，
> 之后该 session 每次提交都返回「前方拥挤请稍后再试」，间隔 15 秒也不解除；
> 重新登录换 session 后单发一次立即成功。所以策略是：提前登录、准点单发、限流换 session。

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
| `BOOK_OPEN_TIME` | 预约窗口开放时刻（`HH:MM`） | `07:00` |
| `BOOK_LOGIN_LEAD` | 开放前多少秒登录 | `60` |
| `BOOK_RETRY_GAP` | 两次提交的最小间隔秒数（不要小于 1） | `1.5` |
| `BOOK_DEADLINE_MIN` | 开放后最多坚持多少分钟 | `10` |

**执行流程**：

```
open-60s   登录、用响应头 Date 校准时钟、生成候选列表
open+0.3s  发第一枪
之后       失败隔 BOOK_RETRY_GAP 秒再发；开放 3 秒内死守第一优先级，之后轮换候选
           「容量不足」→ 剔除该候选，立刻试下一个
           「前方拥挤 / 点击太频繁」→ 等 2 秒重新登录换 session
           「不在服务时间 / 资源不可预约」→ 窗口没开，继续等
open+10min 放弃并推送通知
```

候选列表：有 `BOOK_PREFER_TIMES` 则按其顺序；否则取当前仍有空位的所有时段。
子场地：`BOOK_SUB_IDS` 非空则用之，否则传全部子场地让服务端分配。

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

在开放时刻前 1~2 分钟启动即可，脚本自己等到 `open-60s` 登录、`open+0.3s` 提交：

```crontab
58 6 * * * cd /path/to/ehall && uv run python automations/auto_book.py >> /tmp/auto_book.log 2>&1
```

> macOS 笔记本注意：合盖睡眠时 cron 不会执行，也不会补跑。要么 `pmset repeat wakeorpoweron` 定时唤醒，
> 要么放到不会睡的机器上。预约站的瑞数 WAF 依赖本机 Google Chrome：查询用无头 Chrome 现场解出的 cookie；预约/取消等 POST 需要页面 JS 生成的动态 URL 后缀，经 `waf_browser.py` 在无头 Chrome 页面内发出（登录后即预热，开放时单次提交约 1~2 秒）。

### 定时运行（CodeBuddy Automation）

在 CodeBuddy 中创建 Automation，Prompt 填：

```
Run: uv run python automations/auto_book.py
Working directory: /path/to/ehall
```

Schedule: `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR=6;BYMINUTE=58`

> 注意：CodeBuddy Automation 不支持秒级精度，06:58 启动足够，脚本自己等到开放时刻。

### 通知

设置 `BARK_URL` 后，预约成功/失败均会推送到手机。
