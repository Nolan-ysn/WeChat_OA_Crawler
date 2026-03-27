# WeChat_OA_Crawler 微信公众号实时监听微服务

## 更新日志

### 3.27
新增广告自检机制，可根据当前广告屏蔽词过滤历史记录，过滤时会同步删除对应的PDF文件和JSON文件；
优化历史记录的存储，添加标题与网页链接的映射；
补全爬虫配置文件内容，新增输出配置接口。


### 3.26
升级去重系统，新增标题重复判定机制（不同公众号发出的同一篇文章具有不同的URL）；
优化元数据（发布时间、作者）爬取逻辑，采用“API 透视” + “DOM 强抓”双重保险确保捕获时间戳。

### 3.24 
优化后端“添加/更新公众号”的接口，可直接输入公众号名称，系统自动搜索fakeid并合并入配置文件；
“删除公众号”端口也一并优化，输入公众号名称即可从配置删除。

## 项目简介

这是一个基于 FastAPI 的微信公众号实时监听微服务，用于自动抓取公众号文章并提取结构化数据，为 RAG 知识库提供数据支持。

## 核心功能

- ✅ **配置持久化**：自动保存/加载配置，重启不丢失
- ✅ **去重机制**：基于 URL 的文章去重，避免重复推送
- ✅ **广告过滤**：关键词过滤 + 内容长度过滤
- ✅ **结构化数据提取**：提取文本、图片、表格、元数据
- ✅ **本地 JSON 文件存储**：保存为 JSON 格式，直接用于 RAG 知识库
- ✅ **PDF 文件生成**：生成 PDF 文件，用于后台人工审核
- ✅ **Webhook 推送**：支持实时推送到后端知识库（可选）
- ✅ **完善的日志系统**：同时输出到文件和控制台
- ✅ **RESTful API 接口**：完整的 REST API，支持动态配置

## 系统架构

```
微信公众号文章
    ↓
提取结构化数据（文本、图片、表格、元数据）
    ↓
    ├─→ 保存 JSON 文件（articles/目录）→ 用于 RAG 知识库
    ├─→ 生成 PDF 文件（pdfs/目录）→ 用于人工审核
    └─→ 推送到 Webhook（可选）→ 实时推送
```

## 安装步骤

### 1. 安装 Python 依赖

```bash
pip install fastapi uvicorn requests beautifulsoup4 apscheduler pydantic
```

### 2. 安装 wkhtmltopdf（可选，用于 PDF 生成）

**Windows**:
1. 下载并安装 [wkhtmltopdf](https://wkhtmltopdf.org/downloads.html)
2. 将安装路径添加到系统环境变量 PATH
   - 默认路径：`C:\Program Files\wkhtmltopdf\bin`
   - 或：`C:\Program Files (x86)\wkhtmltopdf\bin`

**macOS**:
```bash
brew install wkhtmltopdf
```

**Linux**:
```bash
sudo apt-get install wkhtmltopdf
```

### 3. 验证安装

```bash
# 验证 Python 依赖
python -c "import fastapi, uvicorn, requests, bs4, apscheduler, pydantic"

# 验证 wkhtmltopdf
wkhtmltopdf -V
```

## 使用方法

### 1. 启动服务

```bash
python crawler_service.py
```

服务将在 `http://localhost:8000` 启动。

### 2. 访问 API 文档

启动后，访问 `http://localhost:8000/docs` 查看 Swagger API 文档。

### 3. 配置公众号

#### 添加公众号

```bash
curl -X POST "http://localhost:8000/api/v1/accounts" \
  -H "Content-Type: application/json" \
  -d '{
    "fakeid": "MzI3MDMzMjg0MA==",
    "name": "示例公众号"
  }'
```

#### 查看公众号列表

```bash
curl "http://localhost:8000/api/v1/accounts"
```

#### 删除公众号

```bash
curl -X DELETE "http://localhost:8000/api/v1/accounts/MzI3MDMzMjg0MA=="
```

### 4. 手动触发爬取

```bash
curl -X POST "http://localhost:8000/api/v1/crawl/trigger"
```

### 5. 修改配置

#### 修改爬取参数

```bash
curl -X PUT "http://localhost:8000/api/v1/settings" \
  -H "Content-Type: application/json" \
  -d '{
    "limit_per_account": 3,
    "crawl_interval_minutes": 10
  }'
```

#### 修改广告过滤配置

```bash
curl -X PUT "http://localhost:8000/api/v1/filter-settings" \
  -H "Content-Type: application/json" \
  -d '{
    "enable_ad_filter": true,
    "ad_keywords": ["广告", "推广", "活动"],
    "min_content_length": 500
  }'
```

#### 修改去重配置

```bash
curl -X PUT "http://localhost:8000/api/v1/dedup-settings" \
  -H "Content-Type: application/json" \
  -d '{
    "enable_dedup": true,
    "max_dedup_records": 10000
  }'
```

## API 接口文档

### 公众号管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `POST /api/v1/accounts` | 添加/更新公众号 |
| `GET /api/v1/accounts` | 获取公众号列表 |
| `DELETE /api/v1/accounts/{fakeid}` | 删除公众号 |

### 配置管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/v1/settings` | 获取当前配置 |
| `PUT /api/v1/settings` | 修改爬取参数 |
| `GET /api/v1/filter-settings` | 获取广告过滤配置 |
| `PUT /api/v1/filter-settings` | 修改广告过滤配置 |
| `GET /api/v1/dedup/stats` | 获取去重统计 |
| `PUT /api/v1/dedup-settings` | 修改去重配置 |
| `DELETE /api/v1/dedup/clear` | 清空去重记录 |

### 爬取控制

| 接口 | 方法 | 说明 |
|------|------|------|
| `POST /api/v1/crawl/trigger` | 手动触发爬取 |
| `GET /api/v1/health` | 健康检查 |

## 数据流说明

### JSON 文件（用于 RAG 知识库）

**路径**：`articles/` 目录

**文件名格式**：`时间戳_文章标题.json`

**数据结构**：
```json
{
  "source": "公众号名称",
  "title": "文章标题",
  "url": "文章链接",
  "content": "纯净文本内容（保留段落结构）",
  "images": [
    {
      "url": "图片URL",
      "alt": "图片描述" #一般为空
    }
  ],
  "tables": [
    {
      "markdown": "表格的Markdown格式",
      "html": "表格的HTML格式"
    }
  ],
  "metadata": {
    "publish_time": "发布时间",
    "author": "作者",
    "word_count": 1234
  }
}
```

**用途**：直接用于 RAG 知识库的 Chunking 和向量化入库。

### PDF 文件（用于人工审核）

**路径**：`pdfs/` 目录

**文件名格式**：`时间戳_文章标题.pdf`

**内容**：原始 HTML 渲染的 PDF（仅包含文字，不包含图片）

**用途**：后台人工审核，查看文章完整内容。

### Webhook 推送（可选）

**配置**：通过 `PUT /api/v1/settings` 设置 `webhook_url`

**数据格式**：与 JSON 文件相同的结构化数据

**用途**：实时推送到后端知识库。

## 常见问题

### 1. PDF 生成失败

**问题**：`No wkhtmltopdf executable found`

**解决方案**：
1. 确认已安装 wkhtmltopdf
2. 将安装路径添加到系统环境变量 PATH
3. 重启 IDE 或终端

**问题**：`ContentNotFoundError`

**原因**：微信文章中的图片无法加载（GIF 文件、防盗链等）

**解决方案**：
- 当前配置已禁用图片加载，只生成文字内容
- PDF 仍然可以正常生成，只是不包含图片

### 2. 429 限流错误

**问题**：Webhook 推送时返回 429 状态码

**原因**：请求频率过高，触发后端限流保护

**解决方案**：
- 降低请求频率（增加 `time.sleep()` 时间）
- 使用本地文件存储代替 Webhook
- 联系后端调整限流阈值

### 3. 配置持久化

**问题**：重启后配置丢失

**解决方案**：
- 配置自动保存到 `crawler_config.json`
- 启动时自动加载配置
- 无需手动配置

### 4. 去重机制

**问题**：相同文章重复推送

**解决方案**：
- 基于 URL 和标题的双重去重机制
- 已处理的 URL 和标题保存在 `processed_urls.json`
- 自动跳过重复文章

## 配置说明

### 核心配置（crawler_config.json）

```json
{
  "target_accounts": {
    "xxxxx": "公众号名称1",
    "xxxxx": "公众号名称2"
  },
  "limit_per_account": 2,
  "crawl_interval_minutes": 5,
  "webhook_url": "https://your-webhook-url.com",
  "ad_keywords": ["广告", "推广", "活动"],
  "min_content_length": 500
}
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `target_accounts` | dict | {} | 目标公众号列表 {fakeid: name} |
| `limit_per_account` | int | 2 | 每次每个公众号抓取的文章数量 (1-10) |
| `crawl_interval_minutes` | int | 5 | 爬取间隔时间 (1-1440 分钟) |
| `webhook_url` | str | "" | Webhook 接收地址 |
| `ad_keywords` | list | [...] | 广告关键词列表 |
| `min_content_length` | int | 500 | 最小内容长度 (0-10000 字符) |
| `enable_dedup` | bool | true | 是否启用去重 |
| `max_dedup_records` | int | 10000 | 最大去重记录数 (100-100000) |
| `enable_ad_filter` | bool | true | 是否启用广告过滤 |
| `enable_pdf_generation` | bool | true | 是否启用 PDF 生成 |
| `output_modes` | list | ["file"] | 输出模式：file, webhook |
| `output_file_dir` | str | "articles" | JSON 文件保存目录 |
| `pdf_output_dir` | str | "pdfs" | PDF 文件保存目录 |

## 文件结构

```
WeChat_OA_Crawler/
├── crawler_service.py          # 主程序文件
├── crawler_config.json        # 配置文件（自动生成）
├── processed_urls.json        # 去重记录（自动生成）
├── crawler.log              # 日志文件（自动生成）
├── articles/                # JSON 文件目录（RAG 用）
│   └── 时间戳_文章标题.json
├── pdfs/                   # PDF 文件目录（人工审核用）
│   └── 时间戳_文章标题.pdf
└── README.md                # 本文档
```

## 日志说明

日志同时输出到：
1. **文件**：`crawler.log`
2. **控制台**：标准输出

日志级别：INFO（包含所有关键操作和错误）

## 技术栈

- **Python 3.x**
- **FastAPI**：Web 框架
- **Uvicorn**：ASGI 服务器
- **Requests**：HTTP 请求
- **BeautifulSoup4**：HTML 解析
- **APScheduler**：定时任务调度
- **Pydantic**：数据验证

## 许可证

本项目仅供学习使用。

## 联系方式

如有问题，请查看日志文件 `crawler.log` 或通过 API 接口获取配置信息。
