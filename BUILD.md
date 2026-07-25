# 打包说明

## 🚀 自动化打包（推荐）

### 方式一：打 Tag 自动发布
```bash
# 创建版本 tag（例如 v1.0.0）
git tag v1.0.0
git push origin v1.0.0
```

推送 tag 后，GitHub Actions 会自动：
1. 并行在 Windows、macOS、Linux 三个平台上打包
2. 创建 GitHub Release
3. 上传所有平台的安装包到 Release 页面

下载地址：`https://github.com/jingchen0529/ticket-lens/releases`

### 方式二：手动触发打包
访问 GitHub Actions 页面，选择对应的 workflow 手动运行：
- `Build Windows Desktop` - 只打 Windows 包
- `Build macOS Desktop` - 只打 macOS 包  
- `Build Linux Desktop` - 只打 Linux 包
- `Release All Platforms` - 打所有平台并发布

## 💻 本地打包

### 开发模式
```bash
cd frontend
npm install
npm run tauri:dev
```

## 多平台打包

### macOS 打包
```bash
cd frontend
npm run tauri:build:macos
```
- **输出位置**: `frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/`
- **产物**: `daxi_*.dmg` (通用二进制，支持 Intel 和 Apple Silicon)

### Windows 打包
> ⚠️ 必须在 Windows 系统上执行

```bash
cd frontend
npm run tauri:build:windows
```
- **输出位置**: `frontend/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/msi/`
- **产物**: `daxi_*.msi`

### Linux 打包
> ⚠️ 必须在 Linux 系统上执行

```bash
cd frontend
npm run tauri:build:linux
```
- **输出位置**: 
  - DEB: `frontend/src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/deb/`
  - AppImage: `frontend/src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/appimage/`

## Git 策略

### 已排除的文件
- ✅ 所有 `target/` 编译产物（约 5.9GB）
- ✅ 所有平台安装包（`.dmg`, `.exe`, `.msi`, `.deb`, `.AppImage` 等）
- ✅ Backend 打包产物 `backend/packaging/dist/`

### 限制
- Git 仓库只接受 **10MB 以下**的文件
- 所有打包产物已自动排除，不会意外上传

## 交付方式
打包完成后，通过以下方式交付安装包给客户：
- 网盘（推荐）
- Release 页面（GitHub/GitLab Releases）
- 内部文件服务器
