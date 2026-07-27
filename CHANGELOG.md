# Changelog

本文档记录项目的所有重要变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [Unreleased]

### 待发布
- 改进项目结构和工程化配置

---

## [0.1.0] - 2024-07-26

### 新增
- **桌面应用形态**：Tauri 跨平台打包,支持 Windows / macOS（Intel + Apple Silicon）
- **数据采集功能**：
  - 大麦演出数据采集,支持城市/分类筛选
  - 猫眼演出数据采集
  - 验证码自动识别(冰拓 1358 平台)+ 手动兜底
  - 阿里 x5、baxia、水果滑块验证码处理
  - 美团 Yoda 验证码处理
  - 详情页富化:场次/票档/地址信息补全
- **数据管理**：
  - SQLite 本地存储
  - 按数据来源/城市/分类/状态/关键词筛选
  - 支持按时间范围清除数据
  - 数据导出为 Excel(.xlsx) 和 CSV 格式
- **用户界面**：
  - Vue 3 + Element Plus + Tailwind CSS
  - 采集页:城市选择器 + 页数控制 + 实时日志
  - 查询页:多条件筛选 + 分页表格 + 排序
  - 设置页:验证码模式切换 + 冰拓账号配置 + 主题色调整
- **自动更新**：集成 Tauri updater,支持应用内检查和安装更新
- **跨平台路径管理**：智能处理打包后的资源路径、数据目录、浏览器位置

### 修复
- 采集页数布局优化:左右区域 50/50 平分,输入框加宽完整显示 placeholder
- CI 流水线修复:移除 Intel Mac 构建以解除 Release 阻塞
- 跨平台打包问题修复:Windows 和 macOS 产物正确生成

### 变更
- 应用改名为 **Daolue（道略）**
- 更换应用图标为道略文旅 logo

### 技术栈
- **前端**: Vue 3.5 + Element Plus 2.14 + Tailwind CSS 3.4 + Vite 6
- **后端**: FastAPI 0.115 + Python 3.11
- **采集**: Playwright 1.49 + Chromium
- **打包**: Tauri 2.11 + PyInstaller
- **数据**: SQLite + Pydantic 2.10

---

## [0.0.1] - 2024-07-初

### 初始版本
- 项目初始化
- 基础爬虫架构搭建
- 验证码处理探索和测试

---

[Unreleased]: https://github.com/jingchen0529/ticket-lens/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jingchen0529/ticket-lens/releases/tag/v0.1.0
