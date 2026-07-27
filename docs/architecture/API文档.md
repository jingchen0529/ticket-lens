# API 文档

本文档描述后端 FastAPI 提供的所有 HTTP 接口。

## 基础信息

- **Base URL**: `http://127.0.0.1:8756/api`
- **Content-Type**: `application/json`
- **CORS**: 允许 `tauri://localhost` 和 Vite dev server 源

---

## 一、采集管理 (`/crawl`)

### 1.1 开始采集任务

**POST** `/crawl/start`

启动一个新的采集任务。同时只能有一个任务运行。

**请求体**:
```json
{
  "cities": ["310100", "110100"],  // 城市代码列表
  "max_pages": 10,                 // 每个城市最多采集页数，null表示全部
  "headed": true,                  // 是否有头模式(显示浏览器窗口)
  "sources": ["damai", "maoyan"]   // 数据源列表
}
```

**响应** (202 Accepted):
```json
{
  "status": "started",
  "task_id": "crawl_20240727_173025",
  "message": "采集任务已启动"
}
```

**错误响应**:
- `409 Conflict`: 已有任务在运行
  ```json
  {
    "detail": "已有采集任务正在运行，请等待完成或取消后再试"
  }
  ```
- `400 Bad Request`: 参数错误

---

### 1.2 取消采集任务

**POST** `/crawl/cancel`

取消当前正在运行的采集任务。

**响应** (200 OK):
```json
{
  "status": "cancelled",
  "message": "采集任务已取消"
}
```

**错误响应**:
- `404 Not Found`: 没有正在运行的任务

---

### 1.3 获取任务状态

**GET** `/crawl/status`

查询当前采集任务状态。

**响应** (200 OK):
```json
{
  "status": "running",              // running | idle | completed | failed
  "task_id": "crawl_20240727_173025",
  "progress": {
    "current_city": "北京",
    "current_page": 5,
    "total_pages": 10,
    "items_collected": 234
  },
  "started_at": "2024-07-27T17:30:25",
  "logs": [
    "[17:30:25] 开始采集北京地区",
    "[17:30:30] 第1页: 获取到 24 条数据",
    "[17:30:35] 检测到验证码，等待处理..."
  ]
}
```

---

## 二、数据查询 (`/shows`)

### 2.1 查询演出列表

**GET** `/shows`

根据筛选条件查询演出数据。

**查询参数**:
- `source` (string, optional): 数据来源 (`damai` | `maoyan`)
- `city` (string, optional): 城市名称
- `category` (string, optional): 分类
- `status` (string, optional): 演出状态
- `keyword` (string, optional): 关键词搜索(标题/场馆)
- `start_date_from` (string, optional): 开始日期范围起点 (ISO 8601)
- `start_date_to` (string, optional): 开始日期范围终点
- `page` (int, default=1): 页码
- `page_size` (int, default=20): 每页条数

**响应** (200 OK):
```json
{
  "total": 1234,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": "damai_310100_123456",
      "source": "damai",
      "title": "《剧院魅影》中文版",
      "city": "上海",
      "category": "音乐剧",
      "venue_name": "上海文化广场",
      "start_date": "2024-08-15",
      "end_date": "2024-09-30",
      "show_time": "19:30",
      "status": "正在热卖",
      "url": "https://detail.damai.cn/item.htm?id=123456",
      "crawled_at": "2024-07-27T17:35:12",
      "sessions": [
        {
          "date": "2024-08-15",
          "time": "19:30",
          "weekday": "周四"
        }
      ],
      "tickets": [
        {
          "name": "VIP座",
          "price": "880"
        },
        {
          "name": "一等座",
          "price": "680"
        }
      ],
      "venue_address": "黄浦区复兴中路597号"
    }
  ]
}
```

---

### 2.2 获取演出详情

**GET** `/shows/{show_id}`

获取单个演出的完整信息。

**响应** (200 OK):
```json
{
  "id": "damai_310100_123456",
  "source": "damai",
  "title": "《剧院魅影》中文版",
  // ... 同查询列表的 item 结构
}
```

**错误响应**:
- `404 Not Found`: 演出不存在

---

### 2.3 删除演出数据

**DELETE** `/shows`

批量删除演出数据。

**请求体**:
```json
{
  "source": "damai",           // 可选：按数据来源删除
  "city": "上海",              // 可选：按城市删除
  "date_from": "2024-01-01",   // 可选：删除指定时间范围
  "date_to": "2024-06-30",
  "ids": ["id1", "id2"]        // 可选：按ID列表删除
}
```

**响应** (200 OK):
```json
{
  "deleted_count": 156,
  "message": "成功删除 156 条记录"
}
```

---

### 2.4 导出数据

**POST** `/shows/export`

导出筛选后的演出数据。

**请求体**:
```json
{
  "format": "xlsx",            // xlsx | csv
  "filters": {
    "source": "damai",
    "city": "上海",
    "keyword": "音乐剧"
  }
}
```

**响应** (200 OK):
- Content-Type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (xlsx)
- Content-Type: `text/csv; charset=utf-8` (csv)
- Content-Disposition: `attachment; filename="shows_export_20240727.xlsx"`

返回文件二进制流。

---

## 三、系统设置 (`/settings`)

### 3.1 获取设置

**GET** `/settings`

获取当前系统设置。

**响应** (200 OK):
```json
{
  "captcha_mode": "manual",        // manual | auto
  "bingtop_account": {
    "username": "user@example.com",
    "password": "******",           // 已脱敏
    "captcha_type": "1358"
  },
  "theme_color": "#409EFF",
  "data_dir": "/Users/user/Library/Application Support/daxi"
}
```

---

### 3.2 更新设置

**PUT** `/settings`

更新系统设置。

**请求体**:
```json
{
  "captcha_mode": "auto",
  "bingtop_account": {
    "username": "user@example.com",
    "password": "newpassword",
    "captcha_type": "1358"
  },
  "theme_color": "#67C23A"
}
```

**响应** (200 OK):
```json
{
  "status": "success",
  "message": "设置已保存"
}
```

---

### 3.3 查询冰拓余额

**GET** `/settings/bingtop/balance`

查询打码平台账号余额。

**响应** (200 OK):
```json
{
  "balance": 158.50,
  "unit": "元",
  "status": "active"
}
```

**错误响应**:
- `401 Unauthorized`: 账号密码错误
- `503 Service Unavailable`: 冰拓平台不可用

---

## 四、系统信息 (`/system`)

### 4.1 健康检查

**GET** `/system/health`

检查服务是否正常运行。

**响应** (200 OK):
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3652
}
```

---

### 4.2 获取城市列表

**GET** `/system/cities`

获取支持的城市列表。

**响应** (200 OK):
```json
{
  "hot_cities": [
    {"code": "310100", "name": "上海"},
    {"code": "110100", "name": "北京"},
    {"code": "440100", "name": "广州"}
  ],
  "all_cities": [
    {"code": "110100", "name": "北京"},
    {"code": "120100", "name": "天津"},
    // ...
  ]
}
```

---

### 4.3 获取分类列表

**GET** `/system/categories`

获取演出分类列表。

**响应** (200 OK):
```json
{
  "categories": [
    "音乐会",
    "演唱会",
    "话剧歌剧",
    "音乐剧",
    "舞蹈芭蕾",
    "曲苑杂坛",
    "体育赛事",
    "休闲展览"
  ]
}
```

---

## 五、错误码说明

所有错误响应遵循以下格式:

```json
{
  "detail": "错误描述信息"
}
```

**HTTP 状态码**:
- `200 OK`: 请求成功
- `202 Accepted`: 异步任务已接受
- `400 Bad Request`: 请求参数错误
- `401 Unauthorized`: 认证失败(打码平台账号)
- `404 Not Found`: 资源不存在
- `409 Conflict`: 资源冲突(如任务已在运行)
- `500 Internal Server Error`: 服务器内部错误
- `503 Service Unavailable`: 服务不可用(如依赖的第三方服务)

---

## 六、实时日志 (WebSocket)

**WS** `/ws/crawl/logs`

订阅采集任务的实时日志流。

**连接**: `ws://127.0.0.1:8756/api/ws/crawl/logs`

**消息格式**:
```json
{
  "timestamp": "2024-07-27T17:35:12",
  "level": "info",           // debug | info | warning | error
  "message": "第5页: 获取到 24 条数据"
}
```

**关闭**: 任务完成或取消时服务器主动断开连接

---

## 七、速率限制

- 采集任务: 同时最多 1 个
- 查询接口: 无限制
- 导出接口: 每次最多导出 10000 条记录

---

## 八、开发调试

### 启动开发服务器

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8756
```

### API 文档

启动后访问:
- Swagger UI: http://127.0.0.1:8756/docs
- ReDoc: http://127.0.0.1:8756/redoc

---

## 九、客户端示例

### JavaScript (Fetch)

```javascript
// 开始采集
async function startCrawl() {
  const response = await fetch('http://127.0.0.1:8756/api/crawl/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      cities: ['310100'],
      max_pages: 10,
      headed: true,
      sources: ['damai']
    })
  });
  
  if (response.status === 409) {
    alert('已有任务在运行');
    return;
  }
  
  const data = await response.json();
  console.log('任务已启动:', data.task_id);
}

// 查询演出
async function queryShows() {
  const params = new URLSearchParams({
    city: '上海',
    category: '音乐剧',
    page: 1,
    page_size: 20
  });
  
  const response = await fetch(`http://127.0.0.1:8756/api/shows?${params}`);
  const data = await response.json();
  
  console.log(`共 ${data.total} 条记录`);
  data.items.forEach(show => {
    console.log(`${show.title} - ${show.venue_name}`);
  });
}
```

### Python (httpx)

```python
import httpx

BASE_URL = "http://127.0.0.1:8756/api"

# 开始采集
async def start_crawl():
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_URL}/crawl/start", json={
            "cities": ["310100"],
            "max_pages": 10,
            "headed": True,
            "sources": ["damai"]
        })
        
        if response.status_code == 202:
            data = response.json()
            print(f"任务已启动: {data['task_id']}")
        elif response.status_code == 409:
            print("已有任务在运行")

# 查询演出
async def query_shows():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/shows", params={
            "city": "上海",
            "category": "音乐剧",
            "page": 1,
            "page_size": 20
        })
        
        data = response.json()
        print(f"共 {data['total']} 条记录")
        for show in data['items']:
            print(f"{show['title']} - {show['venue_name']}")
```
