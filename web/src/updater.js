// Tauri 自动更新封装。
//
// 更新链路：CI 发版时用 minisign 私钥签名 updater 产物（macOS .tar.gz /
// Windows NSIS .exe），并组装 latest.json 上传到 OSS 和 GitHub Release。客户端启动时
// （及点「检查更新」时）优先从 OSS 拉清单，GitHub Release 作为备用源，随后
// 比对版本号 + 校验签名 → 下载 → 重启。
//
// 教训（见项目记忆）：Tauri 插件 JS 绑定必须静态 import——本仓库 openExternalUrl
// 就是把动态 import 改成静态 shellOpen 才修好的。这两个包在浏览器 dev 下也能安全
// 加载（只是调用时无效），故顶部静态 import；所有调用仍只在 IN_TAURI 下发生。

import { check } from '@tauri-apps/plugin-updater'
import { relaunch } from '@tauri-apps/plugin-process'
import { IN_TAURI } from './api.js'

// Tauri invoke 的 reject 值既可能是 Error，也可能是普通字符串。统一成 Error，
// 否则设置页读取 e.message 时只会显示没有诊断价值的「检查更新失败」。
function normalizeUpdaterError(error, fallback) {
  if (error instanceof Error) return error

  let message = ''
  if (typeof error === 'string') {
    message = error
  } else if (error && typeof error.message === 'string') {
    message = error.message
  } else if (error != null) {
    try {
      const serialized = JSON.stringify(error)
      if (serialized !== '{}') message = serialized
    } catch {
      // 无法序列化时使用下面的 fallback。
    }
  }

  const normalized = new Error(message || fallback)
  normalized.cause = error
  return normalized
}

// 检查是否有新版本。返回 Update 对象（有更新）或 null（已是最新 / 非 Tauri）。
// 静默失败返回 null，避免离线或 GitHub 不可达时打断使用；showError 打开时抛出。
export async function checkForUpdate({ showError = false } = {}) {
  if (!IN_TAURI) return null
  try {
    const update = await check()
    if (update && update.available) return update
    return null
  } catch (e) {
    const error = normalizeUpdaterError(e, '检查更新失败')
    if (showError) throw error
    console.warn('[updater] 检查更新失败:', error)
    return null
  }
}

// 下载并安装更新，完成后重启应用。onProgress 收到 0-100 的整数（若能算出）。
export async function downloadAndInstall(update, onProgress) {
  try {
    let downloaded = 0
    let contentLength = 0
    // 拆开下载与安装，确保网络和签名校验完成后才进入安装阶段。不要在这里先
    // 停后端：Windows updater 启动 NSIS 后会直接退出进程，UAC 被取消时 JS
    // 无法 catch；后端由父进程监督管道随桌面退出，NSIS hook 再做强制兜底。
    await update.download((event) => {
      switch (event.event) {
        case 'Started':
          contentLength = event.data.contentLength || 0
          break
        case 'Progress':
          downloaded += event.data.chunkLength || 0
          if (onProgress && contentLength > 0) {
            onProgress(Math.min(100, Math.round((downloaded / contentLength) * 100)))
          }
          break
        case 'Finished':
          if (onProgress) onProgress(100)
          break
      }
    })

    await update.install()
    await relaunch()
  } catch (e) {
    throw normalizeUpdaterError(e, '下载安装失败')
  }
}
