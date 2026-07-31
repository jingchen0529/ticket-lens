// 后端 API 封装。两种运行环境：
//   1. 浏览器 + Vite dev：相对 /api，由 vite.config.js 代理到后端。
//   2. Tauri 打包后：前端跑在 tauri://localhost，相对路径打不到后端，
//      必须用绝对地址指向固定端口的本地后端（127.0.0.1:8756）。
//
// 后端路由见 app/routers/：
//   shows.py  只读查询 / facets / 导出
//   crawl.py  触发采集 / 进度轮询

// Tauri 注入 window.__TAURI_INTERNALS__（v2）；据此切换到绝对地址。
export const IN_TAURI =
  typeof window !== 'undefined' &&
  (window.__TAURI_INTERNALS__ !== undefined || window.__TAURI__ !== undefined)

// 后端固定端口，需与 src-tauri 拉起后端时的 --port 一致。
const BACKEND_PORT = 8756
const BASE = IN_TAURI ? `http://127.0.0.1:${BACKEND_PORT}/api` : '/api'

async function request(path, options = {}) {
  const resp = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body && body.detail) detail = body.detail
    } catch {
      // 非 JSON 响应，保留默认 detail
    }
    const err = new Error(detail)
    err.status = resp.status
    throw err
  }
  return resp.json()
}

function qs(params) {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') usp.append(k, v)
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  // --- 只读查询 ---
  health() {
    return request('/health')
  },
  facets() {
    return request('/facets')
  },
  listShows(params = {}) {
    return request('/shows' + qs(params))
  },
  getShow(id) {
    return request(`/shows/${encodeURIComponent(id)}`)
  },
  // 清除采集数据。payload.scope 决定范围（与导出一致）：
  //   all      整库清空（shows / raw_items / crawl_runs），保留城市预设与设置
  //   selected 只删勾选的 ids（payload.ids 逗号分隔）
  //   filtered 删全部匹配筛选条件的记录（keyword/source/city/category/perf_state）
  // 不传 payload 时默认整库清空。
  clearData(payload = {}) {
    return request('/data/clear', { method: 'POST', body: JSON.stringify(payload) })
  },
  // 导出下载地址。浏览器环境直接 window.open 交给浏览器下载；
  // Tauri WebView 不支持网页下载，页面侧需 fetch 此地址后经 dialog+fs 落盘。
  exportUrl(fmt, params = {}) {
    return BASE + '/export' + qs({ fmt, ...params })
  },

  // --- 采集 ---
  startCrawl(payload) {
    return request('/crawl', { method: 'POST', body: JSON.stringify(payload) })
  },
  activeCrawl() {
    return request('/crawl/active')
  },
  listCrawls() {
    return request('/crawl')
  },
  getCrawl(id) {
    return request(`/crawl/${encodeURIComponent(id)}`)
  },
  cancelCrawl(id) {
    return request(`/crawl/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
  },

  // --- 系统设置 ---
  getSettings() {
    return request('/settings')
  },
  updateSettings(payload) {
    return request('/settings', { method: 'POST', body: JSON.stringify(payload) })
  },
  getBingtuoCredentials() {
    return request('/settings/bingtuo')
  },
  getBingtuoBalance() {
    return request('/settings/bingtuo/balance')
  },
}
