# Tools - 开发工具集

本目录存放开发、调试、测试相关的工具脚本,**不用于生产环境**。

## 目录结构

```
tools/
├── dev/          # 开发调试脚本
├── cdp/          # Chrome DevTools Protocol 工具
└── probes/       # 验证码探测工具
```

---

## dev/ - 开发调试脚本

### test_damai_slider_e2e_sqlite.py
**用途**: 大麦水果滑块端到端测试

完整链路测试:触发验证码 → 自动过码 → 续拉 searchajax → 写 SQLite

**用法**:
```bash
cd backend
source .venv/bin/activate

# 有头观察,从高页触发风控(更容易出滑块)
python tools/dev/test_damai_slider_e2e_sqlite.py --headed --start 16 --end 25

# 无头 + 指定固定库路径
python tools/dev/test_damai_slider_e2e_sqlite.py --start 1 --end 3 \
    --db data/daxi_e2e_test.sqlite3
```

### test_bingtop_1358_newslidecaptcha.py
**用途**: 冰拓 1358 新版滑块验证码测试

### bingtop_live_crawl.py
**用途**: 冰拓平台实时爬取测试

### render_captcha_probe.py
**用途**: 验证码渲染探测

### damai_search_paginate.py
**用途**: 大麦搜索分页调试

---

## cdp/ - Chrome DevTools Protocol 工具

Node.js 脚本,直接用 CDP 协议控制浏览器进行自动化操作。

### damai_paginate.js
**用途**: 大麦搜索页翻页自动化

**依赖**:
```bash
cd backend/tools/cdp
npm install
```

---

## probes/ - 验证码探测工具

### probe_live_frames.py
**用途**: 实时探测验证码帧结构

### test_fruit_live.py
**用途**: 水果滑块验证码实时测试

---

## 注意事项

1. 这些脚本仅用于开发调试,不应在生产环境运行
2. 部分脚本需要单独安装依赖(如 cdp/ 下的 Node.js 包)
3. 运行前确保虚拟环境已激活: `source .venv/bin/activate`
4. 测试脚本可能产生大量日志和临时文件,注意清理
