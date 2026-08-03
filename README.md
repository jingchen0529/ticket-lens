# ticket-lens（daxi）

大麦 / 猫眼 **演出数据采集平台**。桌面客户端形态：Tauri 壳 + Vue 3 前端 + FastAPI 后端（PyInstaller 打包）+ Playwright 真实浏览器采集。

一个安装包装完即用，客户在界面上点「开始采集」，遇到验证码弹出真实浏览器窗口手动拖滑块，数据落本地 SQLite，可在界面查询、导出 CSV / Excel。

## 命名说明

历史原因存在四个名字，含义如下（对外统一用 **ticket-lens**，对内统一用 **daxi**）：

| 名字 | 出现位置 | 说明 |
| --- | --- | --- |
| `ticket-lens` | 产品名、本文档标题 | 对客户呈现的名称 |
| `daxi` | CLI 命令、环境变量前缀 `DAXI_`、数据库 `daxi.sqlite3` | 项目代号，内部统一使用 |
| `daxicrawler` | `pyproject.toml` 包名 | Python 分发包名，与 CLI 分离 |
| `damai` | 仓库目录名、`crawlers/damai/` | 历史遗留；爬虫上下文里仅指大麦这个数据源 |

新增代码/文档时：内部标识用 `daxi`，数据源相关才用 `damai` / `maoyan`，不要再引入新别名。

## 形态与约束

- **local-first 单客户**：后端只监听 `127.0.0.1`，无多租户、无鉴权，不面向公网。
- **前后端固定端口 8756**：前端 `web/src/api.js` 的 `BACKEND_PORT` 与 `web/src-tauri/src/main.rs` 的 `BACKEND_PORT` 必须一致，Vite dev 代理也指向它。
- **采集默认有头**：大麦几乎必弹验证码，界面提交任务时 `headed: true`，无头仅适合已有可用 cookie 的场景。
- **同时只允许一个采集任务**：有头浏览器 + 单客户，第二次提交返回 409。

## 目录结构

```
.                   FastAPI + 爬虫（Python 3.11+，uv 管理）
  app/
    cli.py            daxi 命令行入口（crawl / serve / show-config / captcha-test）
    main.py           FastAPI 装配（CORS 放开 vite dev + tauri origin）
    routers/          shows.py 查询导出 / crawl.py 触发采集 / settings.py 前端设置
    crawlers/damai/   大麦采集 + 阿里 x5、baxia、水果滑块过码
    crawlers/maoyan/  猫眼采集 + 美团 Yoda 过码
    pipeline/         RawShowItem → 统一 Show 规范化
    services/         crawl.py 可编程采集入口 / crawl_jobs.py 进程内任务管理 / export.py
    core/paths.py     跨平台路径解析（打包后 data 目录、随包 Chromium）
  packaging/        PyInstaller spec + entry
  configs/default.yaml  配置模板
scripts/          生产运维脚本（数据迁移、详情回填），可直接对客户数据执行
tools/            开发调试工具（dev 调试脚本 / cdp / probes 验证码探测），不进生产
web/       Vue 3 + Element Plus + Vite
  src/views/          CrawlView 采集 / ShowsView 查询 / SettingsView 设置
  src/api.js          后端 API 封装（含 Tauri / 浏览器双环境判断）
  src-tauri/          Tauri 2 壳，负责拉起与回收后端子进程
.github/workflows/release.yml   四平台并行打包 + 发 Release
```

## 本地开发

后端：

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
playwright install chromium

daxi serve --port 8756        # 端口必须是 8756，前端按这个找后端
```

前端：

```bash
cd web
npm install
npm run dev                   # 浏览器调页面，/api 由 vite 代理到 8756
npm run tauri:dev             # 跑桌面壳（dev 模式不自动拉后端，需自己 daxi serve）
```

测试：

```bash
pytest
```

## 命令行采集（不经界面）

```bash
daxi show-config                                    # 看当前生效配置
daxi crawl -s damai -c 北京 -c 上海 -p 1 --headed -v  # 有头，方便手动过码
daxi crawl -s maoyan -c 成都 -p 2 --backend sqlite
daxi crawl                                          # 按配置文件默认城市抓两个源
```

可选环境变量：

```bash
export DAXI_DATA_DIR=/path/to/data      # 覆盖数据目录
export DAXI_HEADLESS=false
export DAXI_PROXY=http://127.0.0.1:7890
export DAXI_CAPTCHA_PROVIDER=bingtop    # 打码平台凭证走环境变量，不写进 yaml
export DAXI_CAPTCHA_USERNAME=...
export DAXI_CAPTCHA_PASSWORD=...
```

## API

后端路由前缀 `/api`，完整交互式文档在 `http://127.0.0.1:8756/docs`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 + 库路径与是否存在 |
| GET | `/api/shows` | 分页查询（source/city/category/status/perf_state/keyword/排序） |
| GET | `/api/shows/{id}` | 单条详情 |
| GET | `/api/facets` | 各维度可选值，供筛选下拉 |
| GET | `/api/export?fmt=csv\|xlsx` | 按同一套筛选条件导出 |
| POST | `/api/crawl` | 提交采集任务，立即返回 job_id |
| GET | `/api/crawl` `/active` `/{id}` | 任务列表 / 当前任务 / 单任务状态 |
| POST | `/api/crawl/{id}/cancel` | 取消 |
| GET·POST | `/api/settings` | 前端设置（打码账号、主题色、过码模式）持久化 |

任务状态目前只有 `pending / running / succeeded / failed` 这一层，没有「第几页 / 当前城市」的细粒度进度，所以界面进度条较粗。

## 数据

统一 `Show` 模型字段：`id`（`{source}:{source_id}`）、`source`、`title`、`category`、`artists`、`venue.{name,city,address}`、`price.{min_price,max_price,raw}`、`status`、`start_time`、`sessions`、`url`、`poster_url`、`extras`。查询时另即时派生 `holiday`（节假日）与 `perf_state`（按当前日期比较出的演出状态），不落库，保证查询与导出口径一致。

导出表头严格对齐《北京市演出信息》36 列模板；场馆综合体、座位数、区号、演艺之都分类等依赖外部主数据的列留空待补。

数据落盘位置由 `app/core/paths.py` 决定，优先级：`DAXI_DATA_DIR` > 可执行文件同级 `data/` > 系统用户目录（Windows `%LOCALAPPDATA%`，装在 Program Files 只读时用）。DB 默认 `data/daxi.sqlite3`，cookie 在 `data/cookies/`。

## 验证码

本项目**不伪造 verify 请求包**，一律真实鼠标拖官方滑块，只是位移来源可选：

| 模式 | 说明 | 付费 |
| --- | --- | --- |
| `local_slider` | 拖动中截图画布、完整度打分找最优 x | 免费 |
| `bingtop` | 冰拓，类型 1358（主图+标题，2 点） | 是 |
| `chaojiying` | 超级鹰，坐标类 9900 | 是 |
| `yunma` | 云码通用滑块 | 是 |

自动过码失败时，有头模式下窗口仍在，客户可直接手动拖过。细节（坐标换算、诊断产物、A/B 对照图）见下方「后端详情」。

## 后端详情

### 架构

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

位移来源二选一/组合：

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
python tools/dev/bingtop_live_crawl.py --start 16 --end 18
# 产物：
#   data/captcha_probe/bingtop_live/last_compare.png   # 人工对照图（红raw/绿ui/蓝reveal）
#   data/captcha_probe/bingtop_live/last_ab_grid.png   # A/B 映射网格
#   data/captcha_probe/bingtop_live/last_drag_compare.json
#   data/captcha_probe/bingtop_live/success_history.jsonl  # 仅 code=0

# 离线用已有样本生成对照（0 点）
python tools/dev/render_captcha_probe.py \
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

### 安装

```bash
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

### 输出

**数据目录**由 `app/core/paths.py` 自动管理:
- **源码运行**: `data/`
- **打包后**: 可执行文件同级 `data/` 或系统用户目录

可通过环境变量 `DAXI_DATA_DIR` 指定自定义位置。

### 输出文件

- `daxi.sqlite3` — SQLite 数据库(主存储)
- `cookies/` — 浏览器 cookie 持久化
  - `damai_storage.json`
  - `maoyan_storage.json`
- `configs/default.yaml` — 用户可编辑配置(首次从模板复制)

**注意**: `data/` 整个目录已被 `.gitignore` 排除，属于运行时产物，不进版本控制。

### 配置

配置模板位于 `configs/default.yaml`，首次运行时会复制到用户数据目录供编辑。详见 [`configs/default.yaml`](configs/default.yaml)。

项目根目录的 `.env.example` 列出了所有可用环境变量:
- `DAXI_DATA_DIR` - 数据存储位置
- `DAXI_LOG_LEVEL` - 日志级别
- `PLAYWRIGHT_BROWSERS_PATH` - 浏览器路径
- `BINGTOP_USERNAME/PASSWORD` - 打码平台账号

复制 `.env.example` 为 `.env` 并填入实际值。

### 开发

```bash
pytest
```

## 打包与发布

推 tag 触发 `.github/workflows/release.yml`，四个 runner 并行原生打包并创建 Release：

```bash
git tag v1.0.0 && git push origin v1.0.0
```

| 产物 | runner | 安装包 |
| --- | --- | --- |
| windows-x86_64 | windows-latest | `.exe`（NSIS） |
| macos-aarch64 | macos-14 | `.dmg` |
| macos-x86_64 | macos-13 | `.dmg` |
| linux-x86_64 | ubuntu-22.04 | `.deb` + `.AppImage` |

打包上有几条硬约束，改动前务必知道：

- **PyInstaller 不能跨平台、也不能跨架构**，所以每个目标都在对应 runner 上原生打后端；macOS 不打 universal 包（universal 壳 + 单架构后端会在另一架构的机器上起不来后端）。
- **有头 Chromium 和无头 headless_shell 是两个不同的二进制**，客户场景两个都要用（平时无头采集、验证码时弹有头窗口），CI 里有一步断言两者都在，缺任一直接 fail。
- Chromium 不塞进 PyInstaller 归档，而是作为独立目录放在后端 exe 同级的 `ms-playwright/`，运行时 `paths.setup_browser_env()` 把 `PLAYWRIGHT_BROWSERS_PATH` 指过去。
- macOS 复制 Chromium 用 `ditto` 而不是 `cp -R`，保住 `.app` bundle 的符号链接和权限。
- `tauri.conf.json` 的 `bundle.targets` 保持 `"all"`，具体格式由 CI 按平台传 `--bundles`（Linux 不打 rpm，runner 没有 `rpmbuild`）。
- 资源映射两侧要一起改：conf 把后端映射到资源目录 `backend/`，`main.rs:backend_exe()` 按 `backend` → `daxi` 顺序查找。这类不一致 CI 全绿、包能装，只在客户点开时表现为后端起不来。
- Tauri 插件要**四件套齐活**：Cargo 依赖 + `main.rs` 注册 + capabilities 权限 + npm JS 绑定包，缺一个都是静默失效。

macOS 包目前**未签名未公证**（需要 Apple 开发者账号），客户首次打开要右键 → 打开。本地打包步骤与产物路径见 [BUILD.md](BUILD.md)。

## 注意

- 站点有反爬，首次采集建议有头模式，遇验证码手动过一次拿到 cookie 后续更顺。
- 控制频率（配置 `request_delay_seconds`），仅用于合规的数据整理场景，勿高频压测。
- 页面 DOM / 接口结构会变，采集侧已做「XHR 优先 + DOM 回退」，仍可能需要随页面改动微调选择器。
