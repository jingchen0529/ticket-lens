// 引擎日志智能汉化转换字典
export function translateLogText(rawText) {
  if (!rawText) return ''
  let text = String(rawText)

  // 1. subpage parse failed item=xxxx head=
  text = text.replace(/subpage parse failed item=(\w+)(.*)/gi, '⚠️ 演出详情子项解析异常 ID: $1')
  text = text.replace(/subpage parse failed item=(\w+)/gi, '⚠️ 演出详情子项解析异常 ID: $1')

  // 2. damai detail progress 300/300 id=xxxx
  text = text.replace(/damai detail progress (\d+\/\d+) id=(\w+)/gi, '大麦网演出详情页抓取进度: $1 (当前ID: $2)')

  // 3. damai detail enrich done with_sessions=19
  text = text.replace(/damai detail enrich done with_sessions=(\d+)/gi, '大麦网演出详情丰富完成，成功提取 $1 个场次')

  // 4. damai done raw=300
  text = text.replace(/damai done raw=(\d+)/gi, '大麦网演出列表解析完成，累计获取原始记录 $1 条')

  // 5. saved storage_state → /path/to/xxx
  text = text.replace(/saved storage_state → (.*)/gi, '登录凭据/Cookies 已更新并安全缓存 → $1')
  text = text.replace(/saved storage_state/gi, '登录凭据 Cookies 已安全保存缓存')

  // 6. source damai raw=300
  text = text.replace(/source damai raw=(\d+)/gi, '来源 [大麦网] 原始抓取: $1 条记录')
  text = text.replace(/source (.*) raw=(\d+)/gi, '来源 [$1] 原始抓取: $2 条记录')

  // 7. browser stopped / started
  text = text.replace(/browser stopped/gi, '自动化采集浏览器已安全平滑退出')
  text = text.replace(/browser started/gi, '自动化采集浏览器已成功启动')

  // 8. crawl finished raw=300 shows=300 out=/path errors=0
  text = text.replace(/crawl finished raw=(\d+) shows=(\d+) out=(.*) errors=(\d+)/gi, '数据采集成功结束：原始 $1 条，规范化入库 $2 条，异常 $4 条')

  // 9. crawl job done id=xxxx shows=300 errors=0
  text = text.replace(/crawl job done id=(\w+) shows=(\d+) errors=(\d+)/gi, '采集任务执行完毕 (任务ID: $1)，实际成功入库 $2 条')

  // 10. 通用采集动作
  text = text.replace(/fetching page (\d+)/gi, '正在抓取第 $1 页数据...')
  text = text.replace(/fetching list/gi, '正在获取演出列表页面...')
  text = text.replace(/initializing browser/gi, '正在初始化自动化引擎环境...')

  return text
}
