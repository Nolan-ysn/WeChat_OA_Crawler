import time
import json
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from datetime import datetime
import re
import os
from contextlib import asynccontextmanager
from batch_get_fakeid import WeChatFakeIDFetcher

# ==========================================
# 1. 核心状态与配置管理 (模拟数据库)
# ==========================================

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class CrawlerConfig:
    def __init__(self):
        # 配置文件路径
        self.config_file = "crawler_config.json"
        self.dedup_file = "processed_urls.json"
        
        # 鉴权配置 (可通过接口更新,默认从配置文件读取)
        self.token = ""
        self.cookie = ""
        
        # 爬虫策略配置
        self.limit_per_account = 1  # 每次每个公众号抓取最新几块
        self.crawl_interval_minutes = 10  # 更新频率（分钟）
        
        # 目标公众号名单: { "fakeid": "公众号名称" }
        self.target_accounts = {"":""}
        
        # 接收数据后端 Webhook 地址
        self.webhook_url = "https://webhook.site/97a7f918-7119-41a4-b92c-f72f011ceaf1"
        
        # 去重配置
        self.enable_dedup = True  # 是否启用去重
        self.processed_urls = set()  # 已处理的 URL 集合
        self.processed_titles = set()  # 已处理的标题集合
        self.processed_records = []  # URL-Title 映射记录列表
        self.url_to_record = {}  # URL -> record 映射（用于快速查找）
        self.title_to_record = {}  # Title -> record 映射（用于快速查找）
        self.max_dedup_records = 10000  # 最大记录数，防止无限增长
        
        # 广告过滤配置
        self.enable_ad_filter = True  # 是否启用广告过滤
        self.ad_keywords = []
        self.min_content_length = 30  # 最小内容长度（字符数）
        
        # 输出配置
        self.output_modes = ["file"]  # 输出模式：file, webhook
        self.output_file_dir = "articles"  # 文件保存目录
        self.output_file_format = "json"  # 文件格式：json, jsonl
        
        # PDF 生成配置（用于人工审核）
        self.enable_pdf_generation = True  # 是否启用 PDF 生成
        self.pdf_output_dir = "pdfs"  # PDF 保存目录
        self.pdf_keep_days = 30  # PDF 保留天数（自动清理）
        
        # 加载持久化配置
        self.load_config()
        self.load_processed_urls()
    
    def load_config(self):
        """从文件加载配置"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 更新配置
                if 'token' in data:
                    self.token = data['token']
                if 'cookie' in data:
                    self.cookie = data['cookie']
                if 'target_accounts' in data:
                    self.target_accounts.update(data['target_accounts'])
                if 'limit_per_account' in data:
                    self.limit_per_account = data['limit_per_account']
                if 'crawl_interval_minutes' in data:
                    self.crawl_interval_minutes = data['crawl_interval_minutes']
                if 'webhook_url' in data:
                    self.webhook_url = data['webhook_url']
                if 'ad_keywords' in data:
                    self.ad_keywords = data['ad_keywords']
                if 'min_content_length' in data:
                    self.min_content_length = data['min_content_length']
                logger.info(f"✅ 已加载配置文件: {self.config_file}")
        except FileNotFoundError:
            logger.info(f"📝 配置文件不存在，使用默认配置")
            self.save_config()
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {e}")
    
    def save_config(self):
        """保存配置到文件"""
        try:
            data = {
                'token': self.token,
                'cookie': self.cookie,
                'target_accounts': self.target_accounts,
                'limit_per_account': self.limit_per_account,
                'crawl_interval_minutes': self.crawl_interval_minutes,
                'webhook_url': self.webhook_url,
                'ad_keywords': self.ad_keywords,
                'min_content_length': self.min_content_length
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 配置已保存到: {self.config_file}")
        except Exception as e:
            logger.error(f"❌ 保存配置文件失败: {e}")
    
    def load_processed_urls(self):
        """从文件加载已处理的去重库（使用 URL-Title 映射格式）"""
        self.processed_urls = set()
        self.processed_titles = set()
        self.processed_records = []
        self.url_to_record = {}
        self.title_to_record = {}
        
        try:
            with open(self.dedup_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.processed_records = data.get("mapping", [])
                for record in self.processed_records:
                    if record.get("url"):
                        self.url_to_record[record["url"]] = record
                        self.processed_urls.add(record["url"])
                    if record.get("title"):
                        self.title_to_record[record["title"]] = record
                        self.processed_titles.add(record["title"])
            logger.info(f"📝 已加载 {len(self.processed_urls)} 条 URL 记录，{len(self.processed_titles)} 条标题记录")
        except FileNotFoundError:
            logger.info(f"📝 去重记录文件不存在，将创建新文件")
        except Exception as e:
            logger.error(f"❌ 加载去重记录失败: {e}")
    
    def save_processed_urls(self):
        """保存去重记录（包含 URL-Title 映射）"""
        try:
            data = {
                "urls": list(self.processed_urls),
                "titles": list(self.processed_titles),
                "mapping": self.processed_records
            }
            with open(self.dedup_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ 保存去重记录失败: {e}")
    
    def is_duplicate(self, url: str, title: str) -> bool:
        """双重防线：检查 URL 或 标题 是否重复"""
        if not self.enable_dedup:
            return False
        return (url in self.processed_urls) or (title in self.processed_titles)
    
    def mark_as_processed(self, url: str, title: str):
        """标记文章为已处理"""
        if self.enable_dedup:
            # 创建映射记录
            record = {"url": url, "title": title}
            self.processed_records.append(record)
            self.url_to_record[url] = record
            if title:
                self.title_to_record[title] = record
            
            self.processed_urls.add(url)
            self.processed_titles.add(title)
                
            # 限制记录数量，防止内存溢出
            if len(self.processed_records) > self.max_dedup_records:
                # 删除最旧的记录
                old_record = self.processed_records.pop(0)
                if old_record.get("url"):
                    self.processed_urls.discard(old_record["url"])
                    self.url_to_record.pop(old_record["url"], None)
                if old_record.get("title"):
                    self.processed_titles.discard(old_record["title"])
                    self.title_to_record.pop(old_record["title"], None)
                    
            self.save_processed_urls()
        
    def is_advertisement(self, title: str, content: str) -> bool:
        """判断是否为广告推文"""
        if not self.enable_ad_filter:
            return False
        
        # 关键词过滤
        for keyword in self.ad_keywords:
            if keyword in title:
                logger.info(f"🚫 过滤广告推文（关键词匹配）：《{title}》")
                return True
        
        # 内容长度过滤
        if len(content) < self.min_content_length:
            logger.info(f"🚫 过滤广告推文（内容过短，{len(content)} 字）：《{title}》")
            return True
        
        return False

# 全局配置实例
config = CrawlerConfig()
scheduler = BackgroundScheduler()

# Lifespan 事件处理器
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    scheduler.add_job(fetch_and_push_data, 'interval', minutes=config.crawl_interval_minutes, id='crawl_job')
    scheduler.start()
    print("🕒 爬虫后台调度器已启动！")
    yield
    # 关闭时执行
    scheduler.shutdown()

app = FastAPI(
    title="微信公众号实时监听微服务",
    description="提供给后端的RAG数据采集接口",
    lifespan=lifespan
)

# ==========================================
# 2. 辅助函数：提取结构化数据
# ==========================================
def extract_images(soup):
    """提取文章中的所有图片"""
    images = []
    content_div = soup.find('div', class_='rich_media_content')
    if not content_div:
        return images
    
    for img in content_div.find_all('img'):
        # 微信公众号图片通常使用 data-src
        img_url = img.get('data-src') or img.get('src')
        if img_url:
            images.append({
                "url": img_url,
                "alt": img.get('alt', '')
            })
    
    return images

def table_to_markdown(table):
    """将 HTML 表格转换为 Markdown 格式"""
    rows = []
    for row in table.find_all('tr'):
        cells = []
        for cell in row.find_all(['td', 'th']):
            cell_text = cell.get_text(strip=True)
            cells.append(cell_text)
        rows.append('| ' + ' | '.join(cells) + ' |')
    
    if not rows:
        return ""
    
    # 添加表头分隔线
    if len(rows) > 1:
        separator = '|' + '|'.join(['---'] * len(rows[0].split('|')[1:-1])) + '|'
        rows.insert(1, separator)
    
    return '\n'.join(rows)

def extract_tables(soup):
    """提取文章中的所有表格"""
    tables = []
    content_div = soup.find('div', class_='rich_media_content')
    if not content_div:
        return tables
    
    for table in content_div.find_all('table'):
        markdown_table = table_to_markdown(table)
        tables.append({
            "markdown": markdown_table,
            "html": str(table)
        })
    
    return tables

def extract_text_with_structure(soup):
    """提取文本（核武器全兼容版：专治个人号和第三方排版工具）"""
    
    # 1. 终极包容：覆盖微信所有的图文、视频分享、小红书模式容器
    content_div = soup.find('div', class_='rich_media_content') or \
                  soup.find(id='js_content') or \
                  soup.find(id='js_share_content') or \
                  soup.find('div', class_='share_notice')
    
    if not content_div:
        return ""
    
    # 2. 暴力吸取：无视所有 HTML 标签（不管是 p 还是 section），强制抽出所有文字
    # 用 '\n' 替代所有的换行标签，保留物理段落！
    raw_text = content_div.get_text(separator='\n', strip=True)
    
    # 3. 排版清洗：第三方工具会产生极多无用的连续换行，我们把它压缩成干净的 Markdown 格式
    clean_text = re.sub(r'\n{2,}', '\n\n', raw_text)
    
    return clean_text


def extract_metadata(soup, msg_data=None):
    """提取文章元数据（API 数据 + DOM 结构双重保险版）"""
    metadata = {}
    
    # 1. 提取作者/公众号名称
    author_tag = soup.find(id='js_name') or \
                 soup.find('strong', class_='profile_nickname') or \
                 soup.find('span', class_='rich_media_meta_nickname')
    
    if author_tag:
        metadata['author'] = author_tag.get_text(strip=True)
    else:
        metadata['author'] = "未知公众号"
    
    # 2. 提取发布时间 (直接用 API 传过来的精确时间戳)
    publish_time = ""
    
    # 直接解析微信后台 API 给的 update_time (100% 准确)
    if msg_data and msg_data.get('update_time'):
        timestamp = msg_data.get('update_time')
        publish_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    # 如果 API 没给，去 DOM 树里硬挖
    if not publish_time:
        time_tag = soup.find(id='publish_time')
        if time_tag:
            publish_time = time_tag.get_text(strip=True)
            
    metadata['publish_time'] = publish_time if publish_time else "近期发布"
    
    return metadata

def save_to_local_file(payload):
    """保存文章到本地 JSON 文件"""
    try:
        # 创建输出目录
        os.makedirs(config.output_file_dir, exist_ok=True)
        
        # 生成文件名（使用时间戳）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_title = "".join(c for c in payload['title'] if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{timestamp}_{safe_title}.json"
        filepath = os.path.join(config.output_file_dir, filename)
        
        # 保存到文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ 已保存到本地文件: {filename}")
        return True
    except Exception as e:
        logger.error(f"❌ 保存到本地文件失败: {e}")
        return False
    
def clean_html_for_pdf(soup, title):
    
    content_div = soup.find('div', class_='rich_media_content') or soup.find(id='js_content') or soup.find(id='js_share_content')
    if not content_div:
        return f"<html><body><h2>{title}</h2><p>正文提取失败</p></body></html>"

    # 1. 修复图片
    for img in content_div.find_all('img'):
        real_src = img.get('data-src')
        if real_src:
            img['src'] = real_src

    # 2. 物理毁灭所有的多媒体、脚本
    for tag in content_div.find_all(['script', 'style', 'iframe', 'video', 'audio', 'noscript']):
        tag.decompose()

    # 3. 扒光所有【子标签】的衣服
    allowed_attrs =['src', 'href', 'colspan', 'rowspan']
    for tag in content_div.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed_attrs}

    content_div.attrs = {}

    # 4. 使用我们自己写的、绝对安全的样式
    clean_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        <style>
            body {{ 
                font-family: "Microsoft YaHei", "SimHei", sans-serif; 
                padding: 20px; 
                line-height: 1.8; 
                color: #000000; 
                font-size: 16px;
                background-color: #ffffff;
            }}
            img {{ 
                max-width: 100%; 
                height: auto; 
                display: block; 
                margin: 20px auto; 
            }}
            p {{ margin-bottom: 15px; text-align: justify; word-wrap: break-word; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #dddddd; padding: 10px; text-align: left; }}
        </style>
    </head>
    <body>
        <h2 style="text-align: center; border-bottom: 2px solid #eeeeee; padding-bottom: 20px; margin-bottom: 30px;">
            {title}
        </h2>
        {str(content_div)}
    </body>
    </html>
    """
    return clean_html

def generate_pdf(html_content, title, url):
    """将 HTML 内容转换为 PDF 文件（用于人工审核）"""
    try:
        import pdfkit
        pdf_config = pdfkit.configuration(wkhtmltopdf=r'D:\wkhtmltopdf\bin\wkhtmltopdf.exe')
        # 创建 PDF 目录
        os.makedirs(config.pdf_output_dir, exist_ok=True)
        
        # 生成文件名（使用时间戳）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{timestamp}_{safe_title}.pdf"
        filepath = os.path.join(config.pdf_output_dir, filename)
        
        # 配置 PDF 选项
        options = {
            'encoding': 'UTF-8',
            'quiet': '',
            'margin-top': '0.75in',
            'margin-right': '0.75in',
            'margin-bottom': '0.75in',
            'margin-left': '0.75in',
            'enable-local-file-access': True,  # 允许加载本地文件
            'disable-smart-shrinking': None,  # 禁用智能缩放，保持原始大小
             # 'no-images': None,  # 禁用图片
            'disable-external-links': None,  # 禁用外部链接
            'load-error-handling': 'ignore'  # 忽略加载错误
        }
        
        # 生成 PDF
        try:
            pdfkit.from_string(html_content, filepath, options=options, configuration=pdf_config)
        except OSError as e:
            # wkhtmltopdf 只要有1个资源加载失败就会报 Exit with code 1
            # 但实际上 PDF 已经完美生成，所以我们直接拦截这个错误。
            if "Exit with code 1" in str(e) and os.path.exists(filepath):
                logger.warning(f" PDF 生成完毕，但包含部分网络加载警告 (不影响阅读): {filename}")
            else:
                raise e # 真正致命的错误才抛出
        
        
        # 获取文件大小
        file_size = os.path.getsize(filepath)
        
        logger.info(f"已生成 PDF: {filename} ({file_size / 1024:.2f} KB)")
        return {
            "filepath": filepath,
            "filename": filename,
            "size": file_size
        }
    except ImportError:
        logger.warning("⚠️ 未安装 pdfkit,跳过 PDF 生成。请运行: pip install pdfkit")
        return None
    except Exception as e:
        logger.error(f"❌ 生成 PDF 失败: {e}")
        return None

# ==========================================
# 3. 广告自检功能
# ==========================================
def get_safe_filename(title: str) -> str:
    """将标题转换为安全的文件名格式（与保存文件时保持一致）"""
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
    return safe_title

def find_matching_files(title: str) -> tuple:
    """
    根据标题查找匹配的 JSON 和 PDF 文件
    返回: (json_file, pdf_file) 或 (None, None)
    """
    safe_title = get_safe_filename(title)
    
    json_file = None
    pdf_file = None
    
    # 在 articles 目录查找
    articles_dir = config.output_file_dir
    pdfs_dir = config.pdf_output_dir
    
    if os.path.exists(articles_dir):
        for f in os.listdir(articles_dir):
            if f.endswith('.json') and safe_title in f:
                json_file = os.path.join(articles_dir, f)
                break
    
    # 在 pdfs 目录查找
    if os.path.exists(pdfs_dir):
        for f in os.listdir(pdfs_dir):
            if f.endswith('.pdf') and safe_title in f:
                pdf_file = os.path.join(pdfs_dir, f)
                break
    
    return json_file, pdf_file

def ad_self_check() -> dict:
    """
    广告自检：扫描去重记录，用当前广告屏蔽词检查历史标题，
    匹配则删除去重记录（URL+Title）和对应的文件
    """
    logger.info("🔍 开始广告自检...")
    
    # 获取当前广告屏蔽词
    ad_keywords = config.ad_keywords
    logger.info(f"📋 当前广告屏蔽词 ({len(ad_keywords)} 个): {ad_keywords[:5]}...")
    
    # 加载当前去重记录
    titles = list(config.processed_titles)
    
    scanned_count = len(titles)
    matched_titles = []
    matched_urls = []  # 收集匹配的 URL
    deleted_articles = []
    deleted_pdfs = []
    
    for title in titles:
        # 用广告屏蔽词检查标题
        for keyword in ad_keywords:
            if keyword in title:
                logger.info(f"🚫 匹配广告关键词 [{keyword}]：《{title}》")
                matched_titles.append(title)
                
                # 通过 mapping 找到对应的 URL
                if title in config.title_to_record:
                    record = config.title_to_record[title]
                    if record.get("url"):
                        matched_urls.append(record["url"])
                        logger.info(f"   📎 关联 URL: {record['url']}")
                
                # 查找并删除对应的文件
                json_file, pdf_file = find_matching_files(title)
                
                if json_file and os.path.exists(json_file):
                    try:
                        os.remove(json_file)
                        logger.info(f"   ✅ 已删除: {json_file}")
                        deleted_articles.append(os.path.basename(json_file))
                    except Exception as e:
                        logger.error(f"   ❌ 删除文件失败: {e}")
                
                if pdf_file and os.path.exists(pdf_file):
                    try:
                        os.remove(pdf_file)
                        logger.info(f"   ✅ 已删除 PDF: {pdf_file}")
                        deleted_pdfs.append(os.path.basename(pdf_file))
                    except Exception as e:
                        logger.error(f"   ❌ 删除PDF失败: {e}")
                
                break  # 找到一个匹配就跳出，避免重复处理
    
    # 从去重记录中移除匹配的标题和 URL
    for title in matched_titles:
        config.processed_titles.discard(title)
        config.title_to_record.pop(title, None)
    
    for url in matched_urls:
        config.processed_urls.discard(url)
        config.url_to_record.pop(url, None)
        # 从 mapping 列表中移除
        config.processed_records = [r for r in config.processed_records if r.get("url") != url]
    
    # 保存更新后的去重记录
    config.save_processed_urls()
    
    result = {
        "scanned_count": scanned_count,
        "matched_count": len(matched_titles),
        "removed_titles": matched_titles,
        "removed_urls": matched_urls,
        "deleted_articles": deleted_articles,
        "deleted_pdfs": deleted_pdfs
    }
    
    logger.info(f"✅ 广告自检完成：扫描 {scanned_count} 条记录，匹配 {len(matched_titles)} 条广告")
    logger.info(f"   删除 titles: {len(matched_titles)} 条")
    logger.info(f"   删除 urls: {len(matched_urls)} 条")
    logger.info(f"   删除 articles: {len(deleted_articles)} 个")
    logger.info(f"   删除 pdfs: {len(deleted_pdfs)} 个")
    
    return result

# ==========================================
# 4. 爬虫核心执行逻辑
# ==========================================
def fetch_and_push_data():
    """后台定时执行的爬取任务"""
    if not config.token or not config.cookie:
        logger.warning("⚠️ 爬虫未启动：缺少 Token 或 Cookie 凭证")
        return
        
    logger.info(f"\n[定时任务触发] 开始巡检 {len(config.target_accounts)} 个公众号...")
    headers = {
        "Cookie": config.cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
        "Referer": "https://mp.weixin.qq.com/"
    }
    
    # 统计信息
    total_fetched = 0
    total_pushed = 0
    total_filtered = 0
    total_duplicate = 0
    
    # 遍历所有配置的公众号
    for fakeid, name in config.target_accounts.items():
        logger.info(f"🔍 正在抓取 [{name}] 的最新推文...")
        search_url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
        params = {
            "action": "list_ex", "begin": "0", "count": str(config.limit_per_account),
            "fakeid": fakeid, "type": "9", "query": "",
            "token": config.token, "lang": "zh_CN", "f": "json", "ajax": "1"
        }
        
        try:
            res = requests.get(search_url, headers=headers, params=params, timeout=15)
            data = res.json()

            if "app_msg_list" not in data:
                base_resp = data.get("base_resp", {})
                ret_code = base_resp.get("ret")
                
                if ret_code == 200003:
                    logger.error(f"❌ [{name}] 抓取失败：登录态已失效！请去网页重新复制 Cookie 和 Token！")
                elif ret_code == 200013:
                    logger.error(f"❌ [{name}] 抓取失败：请求太频繁触发微信风控！请暂停程序休息片刻。")
                elif ret_code == 200002:
                    logger.error(f"❌ [{name}] 抓取失败：参数错误，请检查 Fakeid 是否正确。")
                else:
                    logger.warning(f"⚠️ [{name}] 未知异常，微信服务器原始返回：{data}")
                    
                continue  # 跳过当前公众号，继续下一个！

            msg_list = data.get("app_msg_list", [])
            logger.info(f"📊 [{name}] 获取到 {len(msg_list)} 篇文章")
            total_fetched += len(msg_list)
            
            for msg in msg_list:
                title = msg.get("title")
                link = msg.get("link")
                
                # 检查是否重复
                if config.is_duplicate(link, title):
                    logger.info(f"⏭️ 跳过重复文章：《{title}》")
                    total_duplicate += 1
                    continue
                
                # 解析正文并提取结构化数据
                try:
                    detail_res = requests.get(link, headers={"User-Agent": headers["User-Agent"]}, timeout=10)
                    soup = BeautifulSoup(detail_res.text, 'html.parser')
                    
                    # 提取结构化数据
                    text_content = extract_text_with_structure(soup)
                    images = extract_images(soup)
                    tables = extract_tables(soup)
                    metadata = extract_metadata(soup, msg)
                    
                    # 检查是否为广告
                    if config.is_advertisement(title, text_content):
                        total_filtered += 1
                        continue
                    
                    # 构建完整的 Payload
                    payload = {
                        "source": name,
                        "title": title,
                        "url": link,
                        "content": text_content,
                        "images": images,
                        "tables": tables,
                        "metadata": metadata
                    }
                    
                    # 添加字数统计
                    metadata['word_count'] = len(text_content)
                    
                    logger.info(f"提取完成：《{title}》")
                    logger.info(f"   - 文本: {len(text_content)} 字")
                    logger.info(f"   - 图片: {len(images)} 张")
                    logger.info(f"   - 表格: {len(tables)} 个")
                    
                    # 根据配置的输出模式处理数据
                    success = False
                    
                    # 保存到本地文件（JSON，用于 RAG）
                    if "file" in config.output_modes:
                        if save_to_local_file(payload):
                            success = True
                    
                    # 生成 PDF（用于人工审核）
                    if config.enable_pdf_generation:
                        # 获取原始 HTML 内容
                        html_content = clean_html_for_pdf(soup, title)
                        pdf_result = generate_pdf(html_content, title, link)
                        if pdf_result:
                            logger.info(f"PDF 已生成")
                    
                    # 推送到 webhook
                    if "webhook" in config.output_modes and config.webhook_url:
                        try:
                            webhook_res = requests.post(config.webhook_url, json=payload, timeout=10)
                            if webhook_res.status_code == 200:
                                logger.info(f"已将《{title}》推送至后端知识库！")
                                success = True
                            else:
                                logger.error(f"❌ 推送失败《{title}》，状态码：{webhook_res.status_code}")
                        except Exception as e:
                            logger.error(f"❌ 推送《{title}》时发生错误: {e}")
                    
                    # 如果至少有一种方式成功，标记为已处理
                    if success:
                        total_pushed += 1
                        config.mark_as_processed(link, title)
                    else:
                        logger.warning(f"⚠️ 《{title}》所有输出方式均失败")
                        
                    time.sleep(10)  # 防封号休眠
                except Exception as e:
                    logger.error(f"❌ 解析文章《{title}》时发生错误: {e}")
                    
        except Exception as e:
            logger.error(f"❌ 抓取 [{name}] 时发生错误: {e}")
    
    # 输出统计信息
    logger.info(f"\n📈 本次爬取统计：")
    logger.info(f"   总获取：{total_fetched} 篇")
    logger.info(f"   成功推送：{total_pushed} 篇")
    logger.info(f"   过滤广告：{total_filtered} 篇")
    logger.info(f"   跳过重复：{total_duplicate} 篇")
    logger.info(f"   时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# ==========================================
# 5. Pydantic 数据模型 (用于接口参数校验)
# ==========================================
class AccountUpdate(BaseModel):
    fakeid: Optional[str] = None
    name: str

class SettingsUpdate(BaseModel):
    limit_per_account: Optional[int] = Field(None, ge=1, le=10, description="每次每个公众号抓取的文章数量 (1-10)")
    crawl_interval_minutes: Optional[int] = Field(None, ge=1, le=1440, description="爬取间隔时间 (1-1440 分钟)")
    token: Optional[str] = None
    cookie: Optional[str] = None
    webhook_url: Optional[str] = None

class FilterSettingsUpdate(BaseModel):
    enable_ad_filter: Optional[bool] = None
    ad_keywords: Optional[List[str]] = None
    min_content_length: Optional[int] = Field(None, ge=0, le=10000, description="最小内容长度 (0-10000 字符)")

class DedupSettingsUpdate(BaseModel):
    enable_dedup: Optional[bool] = None
    max_dedup_records: Optional[int] = Field(None, ge=100, le=100000, description="最大去重记录数 (100-100000)")

# ==========================================
# 6. 暴露的 RESTful API 接口
# ==========================================
@app.get("/api/v1/accounts", summary="获取当前监听的公众号列表")
def get_accounts():
    return {"current_accounts": config.target_accounts}

@app.post("/api/v1/accounts", summary="添加公众号")
def add_account(account: AccountUpdate):
    '''
    输入公众号名称即可，若保持fakeid为空，系统会自动搜索fakeid
    '''
    fakeid = account.fakeid

    if not fakeid:
        if not config.token or not config.cookie:
            raise HTTPException(status_code=400, detail="系统缺少 Token 或 Cookie 凭证，无法执行自动搜索。请先调用 /settings 配置。")
            
        logger.info(f"🔍 正在自动搜索公众号 [{account.name}] 的 fakeid...")
        
        fetcher = WeChatFakeIDFetcher(token=config.token, cookie=config.cookie)
        result = fetcher.search_account(account.name)
        
        if not result:
            # 因为 fetcher 失败会返回 None，我们直接拦截报错
            raise HTTPException(status_code=404, detail=f"未找到公众号 '{account.name}'，或 Cookie/Token 已过期，请查看终端日志排查。")
            
        fakeid = result["fakeid"]
        account.name = result["name"]  # 自动修正为公众号的官方名字
        logger.info(f"✅ 搜索成功: {account.name} -> {fakeid}")

    # 存入配置并保存
    config.target_accounts[fakeid] = account.name
    config.save_config()
    
    logger.info(f"✅ 成功添加/更新监听列表: {account.name} (fakeid: {fakeid})")
    return {
        "status": "success", 
        "message": f"成功添加公众号: {account.name}", 
        "fakeid": fakeid,
        "current_accounts": config.target_accounts
    }

@app.delete("/api/v1/accounts", summary="删除公众号")
def delete_account_by_name(name: str):
    '''
    输入公众号名称即可
    '''
    fakeids_to_delete =[
        fid for fid, acc_name in config.target_accounts.items() 
        if acc_name == name
    ]
    if not fakeids_to_delete:
        raise HTTPException(status_code=404, detail=f"配置中未找到名为 '{name}' 的公众号，请检查是否输入有误。") 

    for fid in fakeids_to_delete:
        config.target_accounts.pop(fid) 

    config.save_config()   
    logger.info(f"🗑️ 成功删除公众号: {name} (移除了 {len(fakeids_to_delete)} 条记录)")
    
    return {
        "status": "success", 
        "message": f"成功删除公众号: {name}", 
        "current_accounts": config.target_accounts
    }

@app.put("/api/v1/settings", summary="修改爬虫全局参数")
def update_settings(settings: SettingsUpdate):
    if settings.limit_per_account is not None:
        config.limit_per_account = settings.limit_per_account
        logger.info(f"📝 更新 limit_per_account: {settings.limit_per_account}")
    if settings.token is not None:
        config.token = settings.token
        logger.info(f"📝 更新 token")
    if settings.cookie is not None:
        config.cookie = settings.cookie
        logger.info(f"📝 更新 cookie")
    if settings.webhook_url is not None:
        config.webhook_url = settings.webhook_url
        logger.info(f"📝 更新 webhook_url: {settings.webhook_url}")
    
    # 如果更新了频率，需要重启定时任务
    if settings.crawl_interval_minutes is not None:
        config.crawl_interval_minutes = settings.crawl_interval_minutes
        scheduler.reschedule_job('crawl_job', trigger='interval', minutes=config.crawl_interval_minutes)
        logger.info(f"📝 更新 crawl_interval_minutes: {settings.crawl_interval_minutes}")
    
    config.save_config()
    return {
        "status": "success", 
        "message": "爬虫参数已更新", 
        "current_limit": config.limit_per_account, 
        "interval": config.crawl_interval_minutes
    }

@app.get("/api/v1/settings", summary="获取当前爬虫配置")
def get_settings():
    return {
        "limit_per_account": config.limit_per_account,
        "crawl_interval_minutes": config.crawl_interval_minutes,
        "webhook_url": config.webhook_url,
        "target_accounts_count": len(config.target_accounts)
    }

@app.put("/api/v1/filter-settings", summary="修改广告过滤配置")
def update_filter_settings(settings: FilterSettingsUpdate):
    if settings.enable_ad_filter is not None:
        config.enable_ad_filter = settings.enable_ad_filter
        logger.info(f"📝 更新 enable_ad_filter: {settings.enable_ad_filter}")
    if settings.ad_keywords is not None:
        config.ad_keywords = settings.ad_keywords
        logger.info(f"📝 更新 ad_keywords: {settings.ad_keywords}")
    if settings.min_content_length is not None:
        config.min_content_length = settings.min_content_length
        logger.info(f"📝 更新 min_content_length: {settings.min_content_length}")
    
    config.save_config()
    return {
        "status": "success",
        "message": "广告过滤配置已更新",
        "enable_ad_filter": config.enable_ad_filter,
        "ad_keywords": config.ad_keywords,
        "min_content_length": config.min_content_length
    }

@app.get("/api/v1/filter-settings", summary="获取当前广告过滤配置")
def get_filter_settings():
    return {
        "enable_ad_filter": config.enable_ad_filter,
        "ad_keywords": config.ad_keywords,
        "min_content_length": config.min_content_length
    }

@app.post("/api/v1/cleanup/ad-check", summary="广告自检过滤")
def cleanup_ad_check(background_tasks: BackgroundTasks):
    """   
    扫描 processed_urls.json 中的历史记录，用当前广告屏蔽词检查历史标题，
    匹配的文章会：
    1. 从去重记录的 titles 中移除
    2. 从去重记录的 urls 中移除（通过 URL-Title 映射关系）
    3. 从去重记录的 mapping 中移除
    4. 删除对应的 JSON 文件（articles 目录）
    5. 删除对应的 PDF 文件（pdfs 目录）
    
    这允许在发现新广告后，更新屏蔽词，然后触发自检清理历史广告。
    """
    logger.info("🚀 收到广告自检请求")
    background_tasks.add_task(ad_self_check)
    return {
        "status": "success",
        "message": "广告自检任务已在后台启动，请查看日志获取详细结果"
    }

@app.get("/api/v1/dedup/stats", summary="获取历史记录信息")
def get_dedup_stats():
    return {
        "enable_dedup": config.enable_dedup,
        "total_urls": len(config.processed_urls),
        "total_titles": len(config.processed_titles),
        "max_records": config.max_dedup_records
    }

@app.put("/api/v1/dedup-settings", summary="修改历史记录配置")
def update_dedup_settings(settings: DedupSettingsUpdate):
    if settings.enable_dedup is not None:
        config.enable_dedup = settings.enable_dedup
        logger.info(f"📝 更新 enable_dedup: {settings.enable_dedup}")
    if settings.max_dedup_records is not None:
        config.max_dedup_records = settings.max_dedup_records
        logger.info(f"📝 更新 max_dedup_records: {settings.max_dedup_records}")
    
    config.save_config()
    return {
        "status": "success",
        "message": "去重配置已更新",
        "enable_dedup": config.enable_dedup,
        "max_dedup_records": config.max_dedup_records
    }

@app.delete("/api/v1/dedup/clear", summary="清空历史记录")
def clear_dedup_records():
    """清空所有去重记录（URL、Title、Mapping）"""
    config.processed_urls.clear()
    config.processed_titles.clear()
    config.processed_records.clear()
    config.url_to_record.clear()
    config.title_to_record.clear()
    config.save_processed_urls()
    logger.info("🗑️ 已清空所有去重记录")
    return {"status": "success", "message": "已清空所有去重记录（URL、Title、Mapping）"}

@app.post("/api/v1/crawl/trigger", summary="立刻触发一次爬取")
def trigger_crawl(background_tasks: BackgroundTasks):
    # 放入后台执行，接口立刻返回，不阻塞后端的请求
    background_tasks.add_task(fetch_and_push_data)
    logger.info("🚀 手动触发爬取任务")
    return {"status": "success", "message": "已在后台触发抓取任务"}


@app.get("/api/v1/health", summary="状态检查")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "accounts_count": len(config.target_accounts),
        "dedup_enabled": config.enable_dedup,
        "ad_filter_enabled": config.enable_ad_filter
    }

# ==========================================
# 7. 服务启动
# ==========================================
if __name__ == "__main__":
    import uvicorn
    # 启动微服务，运行在 8000 端口
    uvicorn.run(app, host="0.0.0.0", port=8000)
