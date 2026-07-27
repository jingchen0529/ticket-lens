# daxicrawler

大麦 / 猫眼 **演出数据** 采集工具。

- **分策略爬虫**：大麦、猫眼各自一套浏览器采集逻辑
- **浏览器自动化**：Playwright（Chromium），支持有头过验证码
- **统一数据模型**：原始 `RawShowItem` → 规范化 `Show` 后落盘

## 架构

```
CLI (daxi crawl)
    │
    ▼
runner（每个源独立 BrowserSession + cookie）
    │
    ├─ crawlers/damai/
    │     crawler.py      # 采集
    │     captcha.py      # 阿里 x5 / baxia / 滑块自动过验证
    │
    └─ crawlers/maoyan/
          crawler.py      # 采集
          captcha.py      # 美团 Yoda / 滑块自动过验证
                │
                ▼
          RawShowItem[] → pipeline.normalize → Show[] → storage
```

### 策略差异

| | 大麦 | 猫眼 |
|---|---|---|
| 目录 | `crawlers/damai/` | `crawlers/maoyan/` |
| 入口 | `search.damai.cn` | `show.maoyan.com` SPA |
| 验证码 | 阿里 x5 / punish / NC 滑块 | 美团 Yoda / 滑块 |
| 自动过验证 | 拟人轨迹滑块 + 可选打码 API | 同左，选择器不同 |
| Cookie | `data/cookies/damai_storage.json` | `data/cookies/maoyan_storage.json` |

两套策略输出同一 `RawShowItem`，再经 `pipeline` 变成统一 `Show`。

### 自动过验证（大麦水果滑块）

大麦当前是阿里 **captchacapslidev2**（「拖动滑块出现完整的一个 XX 后就松开」）。JS 协议要点：

- 出题：`_____tmd_____/*Get` → `{ encryptToken, imageData, ques }`
- 拖动：`SecCaptcha.updatePos(24/(w/320)-24 + x/scale)`（实时错位渲染）
- 松手：`verify` 提交 `per = round((x+24)/width, 3)` + `width/time/token/ua/umidToken/...`

本项目 **不伪造 verify 包**，一律真实鼠标拖官方滑块（轨迹 + 设备指纹走原链路），位移来源二选一/组合：

| 模式 | 说明 | 付费 |
|---|---|---|
| `local_slider` | 拖动中截图画布，完整度打分找最优 x | 免费 |
| `bingtop` | [冰拓](https://www.bingtop.com) 国内，类型 **1358**（主图+标题，2点）/ 1357 / 1359 | 支付宝/微信 |
| `chaojiying` | [超级鹰](https://www.chaojiying.com) 国内，坐标类 9900 | 国内充值 |
| `yunma` | [云码](https://www.jfbym.com) 国内通用滑块 | token 充值 |

`1358` 推荐 `provider_only`，避免识别失败后切换另一套坐标算法继续拖；纯本地调试可用 `local_only`。
`1358` 坐标按目标右缘换算为 `raw * 显示宽 / 图片宽 - 24`：`24` 是页面协议前缘，不从 DOM 按钮宽度推导；不要再固定多加余量，否则提交的 `per` 会整体偏大。

```yaml
captcha:
  auto: true
  provider: bingtop          # local_slider | bingtop | chaojiying | yunma
  username: ""                 # 使用 DAXI_CAPTCHA_USERNAME
  password: ""                 # 使用 DAXI_CAPTCHA_PASSWORD
  fruit_strategy: provider_only  # local_first | provider_first | local_only | provider_only
  fruit_captcha_type: 1358     # 冰拓：1358 主图+标题(2点)；1357 旧双图；1359 单图
  fruit_scan_step: 4
  fruit_max_rounds: 1          # 默认仅一题，避免持续识别/扣点（可显式设 1~5）
  allow_manual: true
  persist_cookies: true
```

环境变量（避免把密码写进 yaml）：

```bash
export DAXI_CAPTCHA_PROVIDER=bingtop
export DAXI_CAPTCHA_USERNAME=...
export DAXI_CAPTCHA_PASSWORD=...
export DAXI_CAPTCHA_FRUIT_STRATEGY=provider_only
```

需要保存脱敏拖动诊断时再临时设置 `DAXI_CAPTCHA_PROBE=1`；默认不写
`data/captcha_probe/bingtop_live`，避免普通运行和测试污染历史样本。

```bash
# 建议先 headed 观察；cookie 复用后可 headless
daxi crawl -s damai -c 北京 -p 1 --headed -v

# 过码诊断：对照图 + A/B 网格 + validate code
export DAXI_CAPTCHA_PROBE=1
python scripts/bingtop_live_crawl.py --start 16 --end 18
# 产物：
#   data/captcha_probe/bingtop_live/last_compare.png   # 人工对照图（红raw/绿ui/蓝reveal）
#   data/captcha_probe/bingtop_live/last_ab_grid.png   # A/B 映射网格
#   data/captcha_probe/bingtop_live/last_drag_compare.json
#   data/captcha_probe/bingtop_live/success_history.jsonl  # 仅 code=0

# 离线用已有样本生成对照（0 点）
python scripts/render_captcha_probe.py \
  --image data/captcha_probe/bingtop_1358/live_imageData.jpg \
  --ques  data/captcha_probe/bingtop_1358/live_ques.png \
  --raw 191
```

| 产物 | 用途 |
|---|---|
| `last_compare.png` | 题干 + 主图 + raw / ui_x / reveal(=ui+24) 竖线，肉眼看冰拓是否标在目标右缘 |
| `last_ab_grid.png` | A right_edge / B raw / C edge+4 / D-12 / E-36 / F offline 并排 |
| `validate code` | **code=0 才过码**；300/306 等是失败（外层 `success:true` 只表示接口通） |

说明：本地打分是启发式；打码只返回位移，**真正过码仍靠浏览器里的官方 verify**。默认付费预算为一题，失败直接上报；有头模式仍可人工处理。

### 统一 Show 字段（最终产物）

| 字段 | 说明 |
|---|---|
| `id` | `{source}:{source_id}` |
| `source` | `damai` / `maoyan` |
| `title` / `category` / `artists` | 标题、分类、艺人 |
| `venue` | `name` / `city` / `address` |
| `price` | `min_price` / `max_price` / `raw` |
| `status` | onsale / presale / sold_out / … |
| `start_time` / `sessions` | 主时间与场次 |
| `url` / `poster_url` | 详情与海报 |
| `extras` | 原始文案等溯源信息 |

## 安装

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 使用 uv 从锁定文件安装(推荐)
uv pip sync requirements-dev.lock

# 或使用 pip
pip install -r requirements-dev.lock

# 安装浏览器
playwright install chromium
```

**依赖管理**:
- `requirements.lock` - 生产依赖锁定
- `requirements-dev.lock` - 开发依赖锁定(包含 pytest)

添加新依赖后需重新生成锁定文件:
```bash
uv pip compile pyproject.toml -o requirements.lock
uv pip compile pyproject.toml --extra dev -o requirements-dev.lock
```

## 使用

```bash
# 看配置
daxi show-config

# 抓大麦 + 猫眼（配置里的默认城市）
daxi crawl

# 只抓大麦，指定城市与关键词，有头模式（方便过验证码）
daxi crawl -s damai -c 北京 -c 上海 -k 演唱会 --headed -v

# 只抓猫眼，最多 2 页，写 sqlite
daxi crawl -s maoyan -c 成都 -p 2 --backend sqlite

# 无关键词时：大麦默认「演唱会」类目，猫眼走城市列表
daxi crawl -s all -c 北京 -p 1 --headed
```

环境变量（可选）：

```bash
export DAXI_HEADLESS=false
export DAXI_PROXY=http://127.0.0.1:7890
export DAXI_OUTPUT_DIR=data
```

## 输出

### 默认输出位置

**数据目录**由 `app/core/paths.py` 自动管理:
- **源码运行**: `backend/data/`
- **打包后**: 可执行文件同级 `data/` 或系统用户目录

可通过环境变量 `DAXI_DATA_DIR` 指定自定义位置。

### 输出文件

- `daxi.sqlite3` — SQLite 数据库(主存储)
- `cookies/` — 浏览器 cookie 持久化
  - `damai_storage.json`
  - `maoyan_storage.json`
- `configs/default.yaml` — 用户可编辑配置(首次从模板复制)

**注意**: `backend/data/` 整个目录已被 `.gitignore` 排除,属于运行时产物,不进版本控制。

## 配置

### 配置文件

配置模板位于 `configs/default.yaml`,首次运行时会复制到用户数据目录供编辑。

详见 [`configs/default.yaml`](configs/default.yaml)。

### 环境变量

项目根目录的 `.env.example` 列出了所有可用环境变量:
- `DAXI_DATA_DIR` - 数据存储位置
- `DAXI_LOG_LEVEL` - 日志级别
- `PLAYWRIGHT_BROWSERS_PATH` - 浏览器路径
- `BINGTOP_USERNAME/PASSWORD` - 打码平台账号

复制 `.env.example` 为 `.env` 并填入实际值。

## 开发

```bash
pytest
```

## 注意

1. 站点有反爬，**首次建议 `--headed`**，遇到验证码在浏览器里手动过。
2. 请控制频率（`request_delay_seconds`），仅用于个人/合规研究，勿高频压测。
3. 页面 DOM / 接口结构会变；策略里已做「XHR 优先 + DOM 回退」，仍可能需随页面改动微调选择器。
