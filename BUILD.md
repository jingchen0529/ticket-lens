# 打包说明

## 🚀 自动化打包（推荐）

### 方式一：打 Tag 自动发布
```bash
# 创建版本 tag（例如 v1.0.0）
git tag v1.0.0
git push origin v1.0.0
```

推送 tag 后，`Release` workflow 会自动：
1. 并行在 3 个 runner 上打包（见下表）
2. 创建 GitHub Release
3. 上传所有平台的安装包到 Release 页面

| 产物 | runner | 安装包 |
| --- | --- | --- |
| windows-x86_64 | windows-latest | `.exe`（NSIS） |
| macos-aarch64 | macos-14 | `.dmg` |
| linux-x86_64 | ubuntu-22.04 | `.deb` + `.AppImage` |

产物统一命名成 `daxi-<tag>-<label>.<ext>`。

> macOS 不打 universal 包：PyInstaller 后端是单架构的，universal 壳配单架构后端
> 会在另一架构的机器上崩。所以只出 Apple Silicon 版 dmg。
>
> **不出 Intel Mac（macos-13）版**：v1.0.1 实测该 runner 排队 2.5 小时仍未分配，
> 而 publish 依赖全部 matrix job 成功，一个 job 排队就会让整个 Release 发不出去。
> 确实需要 Intel Mac 包时，在 macos-13 上手动跑一次构建，或把它加回 matrix 并接受
> 排队风险（可考虑给该 job 单独设 timeout-minutes + continue-on-error）。

下载地址：`https://github.com/jingchen0529/ticket-lens/releases`

### 方式二：手动触发打包
GitHub Actions 页面手动运行 `Release`（`workflow_dispatch`）。手动触发只跑构建、
产物留在 workflow artifacts 里，不创建 Release（创建 Release 只在 tag 推送时发生）。

## 💻 本地打包

### 开发模式
```bash
cd web/frontend
npm install
npm run tauri:dev
```

## 多平台打包

### macOS 打包
```bash
cd web/frontend
npm run tauri:build:macos
```
- **输出位置**: `web/frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/`
- **产物**: `daxi_*.dmg`

> ⚠️ 这个 script 打的是 universal 壳，但 `packaging/dist/daxi` 里的
> PyInstaller 后端只有当前机器的架构。本地自用没问题，交付给另一种架构的机器会起不了后端。
> 要交付就走 CI（tag 触发），CI 是每个架构各自原生打的。

### Windows 打包
> ⚠️ 必须在 Windows 系统上执行

```bash
cd web/frontend
npm run tauri:build:windows
```
- **输出位置**: `web/frontend/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`
- **产物**: `daxi_*-setup.exe`

### Linux 打包
> ⚠️ 必须在 Linux 系统上执行

```bash
cd web/frontend
npm run tauri:build:linux
```
- **输出位置**: 
  - DEB: `web/frontend/src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/deb/`
  - AppImage: `web/frontend/src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/appimage/`

## Git 策略

### 已排除的文件
- ✅ 所有 `target/` 编译产物（约 5.9GB）
- ✅ 所有平台安装包（`.dmg`, `.exe`, `.msi`, `.deb`, `.AppImage` 等）
- ✅ Backend 打包产物 `packaging/dist/`

### 限制
- Git 仓库只接受 **10MB 以下**的文件
- 所有打包产物已自动排除，不会意外上传

## 交付方式
打包完成后，通过以下方式交付安装包给客户：
- 网盘（推荐）
- Release 页面（GitHub/GitLab Releases）
- 内部文件服务器
