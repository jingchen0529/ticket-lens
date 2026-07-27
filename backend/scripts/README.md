# Scripts - 生产运维脚本

本目录存放生产环境和运维场景使用的脚本。

## 可用脚本

### backfill_detail.py
**用途**: 补跑详情富化

为已入库但未富化的演出记录补全场次、票档、地址等详情信息。

**使用场景**:
- 历史数据迁移后需要补全详情
- 采集时详情接口失败需要重新获取

**用法**:
```bash
cd backend
source .venv/bin/activate
python scripts/backfill_detail.py
```

---

## 开发调试脚本

开发和调试用的脚本已移至 `backend/tools/dev/`,包括:
- 验证码测试脚本
- 端到端测试脚本
- 爬虫调试工具

详见 `tools/dev/README.md`
