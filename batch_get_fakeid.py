#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量获取微信公众号 fakeid 的脚本
支持批量搜索、文件读取、交互式添加
"""

import requests
import json
import argparse
import sys
from typing import Dict, List, Optional


class WeChatFakeIDFetcher:
    """微信公众号 fakeid 获取器"""
    
    def __init__(self, token: str, cookie: str):
        """
        初始化
        
        Args:
            token: 微信 token
            cookie: 微信 cookie
        """
        self.token = token
        self.cookie = cookie
        self.headers = {
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
            "Referer": "https://mp.weixin.qq.com/"
        }
        self.search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
    
    def search_account(self, account_name: str) -> Optional[Dict]:
        """
        搜索公众号并获取 fakeid
        
        Args:
            account_name: 公众号名称
            
        Returns:
            包含 fakeid 和名称的字典，失败返回 None
        """
        params = {
            "action": "search_biz",
            "begin": "0",
            "count": "5",
            "query": account_name,
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1"
        }
        
        try:
            response = requests.get(self.search_url, headers=self.headers, params=params, timeout=15)
            data = response.json()
            
            if "list" not in data:
                print(f"❌ 搜索失败：{account_name}")
                print(f"   原因：{data.get('base_resp', {}).get('ret_msg', '未知错误')}")
                return None
            
            accounts = data["list"]
            if not accounts:
                print(f"⚠️ 未找到公众号：{account_name}")
                return None
            
            # 返回第一个匹配的公众号
            account = accounts[0]
            fakeid = account.get("fakeid")
            nickname = account.get("nickname")
            
            if fakeid and nickname:
                print(f"✅ 找到：{nickname} (fakeid: {fakeid})")
                return {
                    "fakeid": fakeid,
                    "name": nickname
                }
            else:
                print(f"❌ 数据不完整：{account_name}")
                return None
                
        except Exception as e:
            print(f"❌ 搜索异常：{account_name}")
            print(f"   错误：{e}")
            return None
    
    def batch_search(self, account_names: List[str]) -> Dict[str, str]:
        """
        批量搜索公众号
        
        Args:
            account_names: 公众号名称列表
            
        Returns:
            {fakeid: name} 字典
        """
        results = {}
        
        print(f"\n🔍 开始批量搜索 {len(account_names)} 个公众号...\n")
        
        for i, name in enumerate(account_names, 1):
            print(f"[{i}/{len(account_names)}] 搜索：{name}")
            result = self.search_account(name)
            
            if result:
                results[result["fakeid"]] = result["name"]
            
            # 避免请求过快
            if i < len(account_names):
                import time
                time.sleep(1)
        
        print(f"\n✅ 搜索完成！成功获取 {len(results)} 个公众号\n")
        return results
    
    def save_to_config(self, accounts: Dict[str, str], config_file: str = "crawler_config.json"):
        """
        保存到配置文件
        
        Args:
            accounts: {fakeid: name} 字典
            config_file: 配置文件路径
        """
        try:
            # 读取现有配置
            existing_config = {}
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
            except FileNotFoundError:
                pass
            
            # 更新 target_accounts
            if "target_accounts" not in existing_config:
                existing_config["target_accounts"] = {}
            
            existing_config["target_accounts"].update(accounts)
            
            # 保存配置
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(existing_config, f, ensure_ascii=False, indent=2)
            
            print(f"✅ 已保存 {len(accounts)} 个公众号到 {config_file}")
            print(f"   当前共有 {len(existing_config['target_accounts'])} 个公众号\n")
            
        except Exception as e:
            print(f"❌ 保存配置失败：{e}\n")


def interactive_mode(fetcher: WeChatFakeIDFetcher): #仅用作算法侧的测试
    """交互式添加公众号"""
    print("\n" + "="*50)
    print("📝 交互式添加公众号")
    print("="*50 + "\n")
    
    accounts = {}
    
    while True:
        print("\n请输入公众号名称（输入 'q' 退出）：")
        name = input("> ").strip()
        
        if name.lower() == 'q':
            break
        
        if not name:
            continue
        
        result = fetcher.search_account(name)
        
        if result:
            print(f"\n是否添加到配置？(y/n)")
            choice = input("> ").strip().lower()
            
            if choice == 'y':
                accounts[result["fakeid"]] = result["name"]
                print(f"✅ 已添加：{result['name']}")
            else:
                print("⏭️ 已跳过")
    
    if accounts:
        print(f"\n📊 共添加 {len(accounts)} 个公众号")
        fetcher.save_to_config(accounts)
    else:
        print("\n⚠️ 未添加任何公众号")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='批量获取微信公众号 fakeid')
    parser.add_argument('--batch', type=str, help='批量搜索（逗号分隔）')
    parser.add_argument('--file', type=str, help='从文件读取公众号名称列表')
    parser.add_argument('--interactive', action='store_true', help='交互式添加')
    parser.add_argument('--token', type=str, help='微信 token（可选，默认从配置文件读取）')
    parser.add_argument('--cookie', type=str, help='微信 cookie（可选，默认从配置文件读取）')
    
    args = parser.parse_args()
    
    # 读取配置文件获取 token 和 cookie
    token = args.token
    cookie = args.cookie
    
    if not token or not cookie:
        try:
            with open("crawler_config.json", 'r', encoding='utf-8') as f:
                config = json.load(f)
                if not token:
                    token = config.get("token")
                if not cookie:
                    cookie = config.get("cookie")
        except FileNotFoundError:
            pass
    
    if not token or not cookie:
        print("❌ 错误：缺少 token 或 cookie")
        print("\n请提供以下方式之一：")
        print("1. 命令行参数：--token <token> --cookie <cookie>")
        print("2. 配置文件：crawler_config.json 中包含 token 和 cookie")
        print("\n获取方式：")
        print("1. 登录微信公众平台：https://mp.weixin.qq.com/")
        print("2. 按 F12 打开开发者工具")
        print("3. 在 Network 标签中找到请求，复制 token 和 cookie")
        sys.exit(1)
    
    # 创建获取器
    fetcher = WeChatFakeIDFetcher(token, cookie)
    
    # 根据参数执行不同模式
    if args.batch:
        # 批量搜索模式
        account_names = [name.strip() for name in args.batch.split(',') if name.strip()]
        accounts = fetcher.batch_search(account_names)
        
        if accounts:
            print("是否保存到配置文件？(y/n)")
            choice = input("> ").strip().lower()
            if choice == 'y':
                fetcher.save_to_config(accounts)
    
    elif args.file:
        # 文件读取模式
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                account_names = [line.strip() for line in f if line.strip()]
            
            accounts = fetcher.batch_search(account_names)
            
            if accounts:
                print("是否保存到配置文件？(y/n)")
                choice = input("> ").strip().lower()
                if choice == 'y':
                    fetcher.save_to_config(accounts)
        
        except FileNotFoundError:
            print(f"❌ 文件不存在：{args.file}")
        except Exception as e:
            print(f"❌ 读取文件失败：{e}")
    
    elif args.interactive:
        # 交互式模式
        interactive_mode(fetcher)
    
    else:
        # 显示帮助信息
        parser.print_help()
        print("\n示例：")
        print("1. 批量搜索：python batch_get_fakeid.py --batch \"公众号1,公众号2,公众号3\"")
        print("2. 文件读取：python batch_get_fakeid.py --file accounts.txt")
        print("3. 交互式：python batch_get_fakeid.py --interactive")


if __name__ == "__main__":
    main()