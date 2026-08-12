// 引擎日志智能汉化转换字典
export function translateLogText(rawText) {
  if (!rawText) return ''
  let text = String(rawText)
  const platformLabel = value => {
    const platform = String(value || '').toLowerCase()
    if (platform === 'damai') return '大麦网'
    if (platform === 'maoyan') return '猫眼'
    if (platform === 'showstart') return '秀动'
    return '采集平台'
  }

  // 1. 详情响应可靠性重试。HTTP 200 但非 JSONP 通常是短时风控，
  // 不应该在单次失败时误报为最终的“解析失败”。
  text = text.replace(
    /subpage invalid response item=(\w+)(.*)/gi,
    '详情响应暂不可用，已进入自动重试（项目编号：$1）'
  )
  text = text.replace(
    /subpage empty response item=(\w+)(.*)/gi,
    '详情响应暂时为空，已进入自动重试（项目编号：$1）'
  )
  text = text.replace(
    /subpage request failed item=(\w+)(.*)/gi,
    '详情请求暂时不可用，已进入自动重试（项目编号：$1）'
  )
  text = text.replace(
    /subpage response fail item=(\w+)(.*)/gi,
    '详情业务响应暂时不可用，已进入自动重试（项目编号：$1）'
  )
  text = text.replace(
    /subpage http (\d+) item=(\w+)(.*)/gi,
    '详情请求收到网络状态码 $1，已进入自动重试（项目编号：$2）'
  )
  // 兼容旧后端产生的历史日志。
  text = text.replace(
    /subpage parse failed item=(\w+)(.*)/gi,
    '详情响应格式曾暂不可用（项目编号：$1，旧日志）'
  )
  text = text.replace(
    /subpage retry scheduled item=(\w+) label=(\S+) attempt=(\d+\/\d+) retry_in=([\d.]+)s/gi,
    '详情自动重试：ID $1，子项 $2，第 $3 次，等待 $4 秒'
  )
  text = text.replace(
    /subpage semantic mismatch item=(\w+) label=(\S+)(.*)/gi,
    '详情子项内容不匹配，已进入自动重试 (ID: $1，子项: $2)'
  )
  text = text.replace(
    /subpage retries exhausted item=(\w+) label=(\S+)(.*)/gi,
    '子请求重试已耗尽，将切换大麦移动端详情 (ID: $1，子项: $2)'
  )
  text = text.replace(
    /damai mobile detail fallback item=(\w+) url=(\S+) reason=(.*)/gi,
    'PC 详情不可用，已切换大麦移动端（项目编号：$1，地址：$2）'
  )
  text = text.replace(
    /damai mobile detail success item=(\w+) url=(\S+) sessions=(\d+)/gi,
    '大麦移动端详情获取成功（项目编号：$1，场次：$3 个，地址：$2）'
  )
  text = text.replace(
    /damai mobile detail failed item=(\w+) attempt=(\d+\/\d+) reason=(.*)/gi,
    '大麦移动端详情暂时失败（项目编号：$1，尝试：$2）'
  )
  text = text.replace(
    /damai mobile detail retry item=(\w+) attempt=(\d+\/\d+) retry_in=([\d.]+)s/gi,
    '大麦移动端详情自动重试（项目编号：$1，第 $2 次，等待 $3 秒）'
  )
  text = text.replace(
    /damai mobile detail exhausted item=(\w+) attempts=(\d+) reason=(.*)/gi,
    '大麦移动端详情重试已耗尽（项目编号：$1，已尝试 $2 次）'
  )
  text = text.replace(
    /damai detail skipped item=(\w+) reason=(.*)/gi,
    '大麦网详情获取失败，已跳过项目 $1 并继续下一个'
  )
  text = text.replace(
    /damai detail batch done success=(\d+) skipped=(\d+) total=(\d+)/gi,
    '大麦网详情批次完成：成功 $1 个，跳过 $2 个，共 $3 个'
  )
  text = text.replace(
    /damai detail processing (\d+\/\d+) id=(\w+)/gi,
    '正在处理大麦网详情：$1（项目编号：$2）'
  )
  text = text.replace(
    /damai detail project retry item=(\w+) attempt=(\d+\/\d+) cooldown=([\d.]+)s reason=(.*)/gi,
    '项目详情整体重试：ID $1，第 $2 次，冷却 $3 秒'
  )
  text = text.replace(
    /damai detail rejected item=(\w+) attempts=(\d+) reason=(.*)/gi,
    '项目详情完整性校验未通过，已拒绝入库 (ID: $1，尝试 $2 轮)'
  )
  text = text.replace(
    /source (damai|maoyan|showstart) item=(\S+) persisted sessions=(\d+) rows=(\d+)/gi,
    (_match, platform, id, sessions, rows) =>
      `${platformLabel(platform)}项目已入库：项目编号 ${id}，场次 ${sessions} 个，数据 ${rows} 条`
  )
  text = text.replace(
    /damai detail item=(\S+) venue=(.*?) addr=(.*?) sessions=(\d+)(?: complete=(\S+) dates=(\d+\/\d+) ticket_sessions=(\d+\/\d+))? troupe=(.*?) organizers=(.*)/gi,
    (_match, id, venue, _addr, sessions, complete, dates, tickets) => {
      const suffix = complete
        ? `，日期 ${dates}，票档场次 ${tickets}，完整性：${String(complete).toLowerCase() === 'true' ? '是' : '否'}`
        : ''
      return `大麦网项目详情处理完成：项目编号 ${id}，场馆 ${venue || '未提供'}，场次 ${sessions} 个${suffix}`
    }
  )

  // 2. damai detail progress 300/300 id=xxxx
  text = text.replace(/damai detail progress (\d+\/\d+) id=(\w+)/gi, '大麦网演出详情页抓取进度: $1 (当前ID: $2)')

  // 3. damai detail enrich done with_sessions=19
  text = text.replace(/damai detail enrich done with_sessions=(\d+)/gi, '大麦网演出详情丰富完成，成功提取 $1 个场次')

  // 4. damai done raw=300
  text = text.replace(/damai done raw=(\d+)/gi, '大麦网演出列表解析完成，累计获取原始记录 $1 条')

  // 5. saved storage_state → /path/to/xxx
  text = text.replace(/saved storage_state → (.*)/gi, '登录凭据和 Cookie 已安全保存')
  text = text.replace(/saved storage_state/gi, '平台登录凭据已安全保存')
  text = text.replace(
    /loaded cookies for (damai|maoyan|showstart) from (.*)/gi,
    (_match, platform) => `已加载${platformLabel(platform)}登录凭据`
  )

  // 6. source damai raw=300
  text = text.replace(/source damai raw=(\d+)/gi, '大麦网原始数据采集完成：$1 条')
  text = text.replace(/source maoyan raw=(\d+)/gi, '猫眼原始数据采集完成：$1 条')
  text = text.replace(/source (.*) raw=(\d+)/gi, '采集平台原始数据采集完成：$2 条')

  // 7. browser cleanup / started
  text = text.replace(/browser cleanup complete/gi, '自动化采集浏览器资源清理完成')
  text = text.replace(/browser stopped/gi, '自动化采集浏览器已安全平滑退出')
  text = text.replace(
    /browser started headless=(\S+) proxy=(\S+)/gi,
    (_match, headless, proxy) =>
      `自动化采集浏览器已启动（${String(headless).toLowerCase() === 'true' ? '无界面' : '有界面'}，代理：${String(proxy).toLowerCase() === 'true' ? '是' : '否'}）`
  )
  text = text.replace(/browser started/gi, '自动化采集浏览器已成功启动')

  // 8. crawl finished raw=300 shows=300 ledger_visible=280 ledger_hidden=20 out=/path errors=0
  text = text.replace(
    /crawl finished raw=(\d+) shows=(\d+) ledger_visible=(\d+) ledger_hidden=(\d+) out=(.*) errors=(\d+)/gi,
    (_match, raw, shows, visible, hidden, _out, errors) => Number(errors) > 0
      ? `数据采集结束（含异常）：原始 ${raw} 条，入库 ${shows} 条、台账可见 ${visible} 条、隐藏展览休闲/体育 ${hidden} 条，异常 ${errors} 条`
      : `数据采集成功结束：原始 ${raw} 条，入库 ${shows} 条、台账可见 ${visible} 条、隐藏展览休闲/体育 ${hidden} 条，异常 0 条`
  )

  // 兼容旧后端格式
  text = text.replace(
    /crawl finished raw=(\d+) shows=(\d+) out=(.*) errors=(\d+)/gi,
    (_match, raw, shows, _out, errors) => Number(errors) > 0
      ? `数据采集结束（含异常）：原始 ${raw} 条，规范化入库 ${shows} 条，异常 ${errors} 条`
      : `数据采集成功结束：原始 ${raw} 条，规范化入库 ${shows} 条，异常 0 条`
  )

  // 9. crawl job done id=xxxx shows=300 ledger_visible=280 ledger_hidden=20 errors=0
  text = text.replace(
    /crawl job done id=(\w+) shows=(\d+) ledger_visible=(\d+) ledger_hidden=(\d+) errors=(\d+)/gi,
    (_match, id, shows, visible, hidden, errors) => Number(errors) > 0
      ? `采集任务失败（任务编号：${id}），入库 ${shows} 条、台账可见 ${visible} 条、隐藏展览休闲/体育 ${hidden} 条，异常 ${errors} 条`
      : `采集任务执行完毕（任务编号：${id}），入库 ${shows} 条、台账可见 ${visible} 条、隐藏展览休闲/体育 ${hidden} 条`
  )

  // 兼容旧后端格式
  text = text.replace(
    /crawl job done id=(\w+) shows=(\d+) errors=(\d+)/gi,
    (_match, id, shows, errors) => Number(errors) > 0
      ? `采集任务失败（任务编号：${id}），入库 ${shows} 条，异常 ${errors} 条`
      : `采集任务执行完毕（任务编号：${id}），成功入库 ${shows} 条`
  )

  // 10. 通用采集动作
  text = text.replace(/fetching page (\d+)/gi, '正在抓取第 $1 页数据...')
  text = text.replace(/fetching list/gi, '正在获取演出列表页面...')
  text = text.replace(/initializing browser/gi, '正在初始化自动化引擎环境...')
  text = text.replace(/maoyan fetching page=(\d+)/gi, '正在采集猫眼第 $1 页')
  text = text.replace(
    /maoyan crawl city=(\S+) keyword=(\S+) pages=(\S+)/gi,
    '开始采集猫眼：城市 $1，关键词 $2，页数 $3'
  )
  text = text.replace(
    /maoyan page=(\d+) records=(\d+) new_items=(\d+)/gi,
    '猫眼第 $1 页采集完成：返回 $2 条，新增 $3 条'
  )
  text = text.replace(
    /maoyan mobile API crawl: city=(\S+) cityId=(\S+)(?: category=.*? categoryId=\S+)? keyword=(.*)/gi,
    '猫眼列表接口已就绪：城市 $1，关键词 $3'
  )
  text = text.replace(
    /maoyan crawl finished: city=(\S+) total_items=(\d+)/gi,
    '猫眼城市采集完成：$1，共 $2 个项目'
  )
  text = text.replace(/maoyan done raw=(\d+)/gi, '猫眼列表采集完成：原始项目 $1 个')
  text = text.replace(
    /bingtop needs username \+ password/gi,
    '冰拓验证码服务配置不完整：请填写用户名和密码'
  )

  return text
}
