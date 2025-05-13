#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sync-HTTP-MCP 客户端命令模块

提供基于Git增量同步的命令行接口。
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
import base64

from git_sync import GitSyncManager
import client  # 使用现有的client模块进行API调用

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class GitSyncClient:
    """基于Git的增量同步客户端"""
    
    def __init__(self, workspace: str, server_url: str):
        """
        初始化Git同步客户端
        
        Args:
            workspace: 本地工作区路径
            server_url: 远程服务器URL
        """
        self.workspace = Path(workspace).resolve()
        self.server_url = server_url
        self.sync_manager = GitSyncManager(workspace, server_url)
        self.client = client.Client(server_url, workspace, use_delta_sync=False)
        
    def init(self, force: bool = False, remote_path: str = None) -> bool:
        """
        初始化同步环境
        
        Args:
            force: 是否强制初始化
            remote_path: 服务器上的远程目录路径（默认: 与本地工作区同名）
            
        Returns:
            初始化是否成功
        """
        # 初始化本地Git仓库
        if not self.sync_manager.init_repo():
            logger.error("初始化本地Git仓库失败")
            return False
        
        # 确定远程路径
        path = remote_path if remote_path else str(self.workspace.name)
        
        # 初始化远程仓库
        try:
            # 首先尝试使用Git同步专用API
            response = self.client.post("/api/v1/sync/init", {
                "path": path,
                "force": force
            })
            
            # 检查请求是否成功
            if response.get("status") == "success":
                logger.info(f"远程Git仓库初始化成功，路径: {path}")
                return True
            elif "detail" in response and response.get("detail") == "Not Found":
                # API端点不存在，尝试使用通用API创建目录
                logger.warning("服务器不支持Git同步API，尝试使用通用API替代")
                
                # 尝试创建远程目录
                response = self.client.post("/api/v1/files/mkdir", {
                    "path": path
                })
                
                if response.get("status") == "success" or "already exists" in str(response.get("message", "")):
                    logger.info(f"已在远程服务器上创建目录: {path}")
                    
                    # 创建.sync_info文件标记同步点
                    sync_info = {
                        "initialized": True,
                        "last_sync_time": time.time(),
                        "client_version": "0.2.0"
                    }
                    
                    sync_info_content = json.dumps(sync_info, indent=2).encode('utf-8')
                    sync_file_path = f"{path}/.sync_info"
                    
                    # 尝试创建同步信息文件
                    try:
                        encoded_content = base64.b64encode(sync_info_content).decode('utf-8')
                        file_response = self.client.post("/api/v1/files/content", {
                            "path": sync_file_path,
                            "content": encoded_content
                        })
                        
                        if file_response.get("status") == "success":
                            logger.info(f"已在远程服务器上创建同步信息文件")
                            return True
                    except Exception as e:
                        logger.warning(f"创建同步信息文件失败，但目录已创建: {str(e)}")
                        # 目录已创建，认为初始化基本成功
                        return True
                else:
                    logger.error(f"在远程服务器上创建目录失败: {response.get('message', '未知错误')}")
                    return False
            else:
                logger.error(f"远程Git仓库初始化失败: {response.get('message', '未知错误')}")
                return False
        
        except Exception as e:
            logger.error(f"初始化远程仓库时出错: {str(e)}")
            return False
    
    def sync(self, auto_commit: bool = True, verbose: bool = False) -> bool:
        """
        执行Git增量同步
        
        Args:
            auto_commit: 是否自动提交变更
            verbose: 是否显示详细信息
            
        Returns:
            同步是否成功
        """
        # 获取同步状态
        status = self.sync_manager.get_sync_status()
        
        if status.get("status") == "error":
            logger.error(f"获取同步状态失败: {status.get('message', '未知错误')}")
            return False
        
        if status.get("status") == "not_initialized":
            logger.error("本地仓库未初始化，请先运行 init 命令")
            return False
        
        # 检查是否有变更需要同步
        if not status.get("pending_changes", False):
            logger.info("没有变更需要同步")
            return True
        
        # 生成patch
        start_time = time.time()
        logger.info("正在生成变更补丁...")
        patch_info = self.sync_manager.generate_patch()
        
        if not patch_info:
            logger.error("生成补丁失败")
            return False
        
        if patch_info.get("status") == "no_changes":
            logger.info("没有变更需要同步")
            return True
        
        # 显示变更信息
        if verbose:
            files_changed = patch_info.get("files_changed", 0)
            untracked_files = patch_info.get("untracked_files", [])
            logger.info(f"发现 {files_changed} 个文件变更")
            if untracked_files:
                logger.info(f"包含 {len(untracked_files)} 个新增文件")
        
        # 发送patch到服务器
        logger.info("正在同步变更到远程服务器...")
        try:
            payload = {
                "base_commit": patch_info.get("base_commit"),
                "patch_content": patch_info.get("patch_content"),
                "binary_files": patch_info.get("binary_files", [])
            }
            
            response = self.client.post("/api/v1/sync/patch", payload)
            
            if response.get("status") == "success":
                elapsed = time.time() - start_time
                new_commit = response.get("new_commit")
                logger.info(f"同步成功 (耗时: {elapsed:.2f}秒)")
                
                # 如果有新的commit，拉取到本地
                if new_commit and new_commit != patch_info.get("base_commit"):
                    # 为了简化，我们这里不实际拉取远程commit，而是创建一个本地同步点
                    self.sync_manager.create_sync_point("Update from remote sync")
                
                return True
            
            elif response.get("status") == "conflict":
                logger.error("同步失败: 检测到冲突")
                conflicts = response.get("conflicts", [])
                if conflicts:
                    logger.error(f"发现 {len(conflicts)} 个冲突文件:")
                    for conflict in conflicts:
                        logger.error(f"  - {conflict.get('path')}")
                    logger.error("请使用 resolve 命令解决冲突")
                return False
            
            else:
                logger.error(f"同步失败: {response.get('message', '未知错误')}")
                return False
        
        except Exception as e:
            logger.error(f"同步时出错: {str(e)}")
            return False
    
    def status(self, verbose: bool = False) -> bool:
        """
        显示同步状态
        
        Args:
            verbose: 是否显示详细信息
            
        Returns:
            命令是否成功执行
        """
        try:
            # 获取本地状态
            local_status = self.sync_manager.get_sync_status()
            
            if local_status.get("status") == "error":
                logger.error(f"获取本地状态失败: {local_status.get('message', '未知错误')}")
                return False
            
            # 获取远程状态
            try:
                remote_status = self.client.get("/api/v1/sync/status")
            except Exception as e:
                logger.error(f"获取远程状态失败: {str(e)}")
                remote_status = {"status": "error", "message": str(e)}
            
            # 显示状态信息
            logger.info("===== 同步状态 =====")
            
            if local_status.get("status") == "not_initialized":
                logger.info("本地仓库状态: 未初始化")
            else:
                logger.info(f"本地仓库状态: {local_status.get('status')}")
                logger.info(f"最后同步点: {local_status.get('last_sync_commit', '无')}")
                logger.info(f"最后同步时间: {local_status.get('last_sync_time', '无')}")
                
                pending_changes = local_status.get("pending_changes", False)
                logger.info(f"有待同步变更: {'是' if pending_changes else '否'}")
                
                if pending_changes and verbose:
                    total = local_status.get("total_changes", 0)
                    logger.info(f"变更文件总数: {total}")
                    
                    changed_files = local_status.get("changed_files", [])
                    if changed_files:
                        logger.info("\n已跟踪的变更文件:")
                        for f in changed_files:
                            logger.info(f"  {f.get('status')}: {f.get('path')}")
                    
                    untracked_files = local_status.get("untracked_files", [])
                    if untracked_files:
                        logger.info("\n未跟踪的文件:")
                        for f in untracked_files:
                            logger.info(f"  新增: {f}")
            
            logger.info("\n------------------")
            
            if remote_status.get("status") == "error":
                logger.info(f"远程仓库状态: 无法获取 ({remote_status.get('message', '未知错误')})")
            elif remote_status.get("status") == "not_initialized":
                logger.info("远程仓库状态: 未初始化")
            else:
                logger.info(f"远程仓库状态: {remote_status.get('status')}")
                logger.info(f"远程同步点: {remote_status.get('last_sync_commit', '无')}")
                logger.info(f"远程最后同步时间: {remote_status.get('last_sync_time', '无')}")
            
            logger.info("===================")
            
            # 检查同步冲突
            local_commit = local_status.get("last_sync_commit")
            remote_commit = remote_status.get("last_sync_commit")
            
            if local_commit and remote_commit and local_commit != remote_commit:
                logger.warning("警告: 本地和远程同步点不一致，可能存在冲突")
                logger.warning("建议使用 sync 命令更新同步点")
            
            return True
        
        except Exception as e:
            logger.error(f"获取状态时出错: {str(e)}")
            return False
    
    def resolve(self, strategy: str = "interactive") -> bool:
        """
        解决同步冲突
        
        Args:
            strategy: 冲突解决策略 (local/remote/interactive)
            
        Returns:
            解决是否成功
        """
        logger.info(f"使用 {strategy} 策略解决冲突")
        
        # 获取冲突信息
        try:
            conflicts = self.client.get("/api/v1/sync/conflicts")
            
            if not conflicts or not conflicts.get("conflicts"):
                logger.info("没有检测到冲突需要解决")
                return True
            
            conflict_files = conflicts.get("conflicts", [])
            logger.info(f"发现 {len(conflict_files)} 个冲突文件")
            
            resolutions = []
            
            for conflict in conflict_files:
                path = conflict.get("path")
                logger.info(f"处理冲突文件: {path}")
                
                if strategy == "local":
                    # 选择本地版本
                    resolutions.append({
                        "path": path,
                        "resolution": "local"
                    })
                
                elif strategy == "remote":
                    # 选择远程版本
                    resolutions.append({
                        "path": path,
                        "resolution": "remote"
                    })
                
                else:  # interactive
                    # 交互式解决冲突
                    print(f"\n冲突文件: {path}")
                    print("请选择解决方案:")
                    print("  1. 保留本地版本")
                    print("  2. 使用远程版本")
                    print("  3. 跳过此文件")
                    
                    choice = input("请输入选择 (1/2/3): ").strip()
                    
                    if choice == "1":
                        resolutions.append({
                            "path": path,
                            "resolution": "local"
                        })
                    elif choice == "2":
                        resolutions.append({
                            "path": path,
                            "resolution": "remote"
                        })
                    else:
                        logger.info(f"跳过文件: {path}")
            
            # 发送解决方案到服务器
            if resolutions:
                response = self.client.post("/api/v1/sync/resolve", {
                    "conflicts": resolutions
                })
                
                if response.get("status") == "success":
                    logger.info("冲突解决成功")
                    return True
                else:
                    logger.error(f"冲突解决失败: {response.get('message', '未知错误')}")
                    return False
            else:
                logger.warning("没有解决任何冲突")
                return False
        
        except Exception as e:
            logger.error(f"解决冲突时出错: {str(e)}")
            return False
    
    def clean(self) -> bool:
        """
        清理同步状态
        
        Returns:
            清理是否成功
        """
        try:
            # 确认操作
            confirm = input("此操作将重置所有同步状态，是否继续？(y/N): ").strip().lower()
            if confirm != "y":
                logger.info("操作已取消")
                return False
            
            # 清理本地仓库
            logger.info("正在清理本地同步状态...")
            
            # 检查.git目录
            git_dir = self.workspace / ".git"
            if git_dir.exists():
                # 我们不会真的删除.git目录，而是创建一个新的同步点
                self.sync_manager.create_sync_point("Reset sync state")
                logger.info("已重置本地同步状态")
            
            # 清理远程仓库
            logger.info("正在清理远程同步状态...")
            try:
                response = self.client.post("/api/v1/sync/clean", {
                    "confirm": True
                })
                
                if response.get("status") == "success":
                    logger.info("远程同步状态清理成功")
                else:
                    logger.error(f"远程同步状态清理失败: {response.get('message', '未知错误')}")
                    return False
            
            except Exception as e:
                logger.error(f"清理远程同步状态时出错: {str(e)}")
                return False
            
            logger.info("同步状态清理完成")
            return True
        
        except Exception as e:
            logger.error(f"清理同步状态时出错: {str(e)}")
            return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Sync-HTTP-MCP 基于Git的增量同步客户端")
    
    # 全局参数
    parser.add_argument("--workspace", "-w", help="本地工作区路径", default=os.getcwd())
    parser.add_argument("--server", "-s", help="远程服务器URL", default="http://localhost:8081")
    parser.add_argument("--verbose", "-v", help="显示详细信息", action="store_true")
    
    # 子命令
    subparsers = parser.add_subparsers(dest="command", help="要执行的命令")
    
    # init命令
    init_parser = subparsers.add_parser("init", help="初始化同步环境")
    init_parser.add_argument("--force", "-f", help="强制初始化", action="store_true")
    init_parser.add_argument("--remote-path", help="服务器上的远程目录路径（默认: 与本地工作区同名）")
    
    # sync命令
    sync_parser = subparsers.add_parser("sync", help="执行增量同步")
    sync_parser.add_argument("--no-commit", help="不自动提交变更", action="store_true", dest="no_commit")
    
    # status命令
    status_parser = subparsers.add_parser("status", help="显示同步状态")
    
    # resolve命令
    resolve_parser = subparsers.add_parser("resolve", help="解决同步冲突")
    resolve_parser.add_argument("--strategy", "-s", 
                             choices=["local", "remote", "interactive"],
                             default="interactive",
                             help="冲突解决策略")
    
    # clean命令
    clean_parser = subparsers.add_parser("clean", help="清理同步状态")
    
    args = parser.parse_args()
    
    # 检查是否提供了命令
    if args.command is None:
        parser.print_help()
        return 1
    
    # 创建客户端实例
    client = GitSyncClient(args.workspace, args.server)
    
    # 执行命令
    if args.command == "init":
        success = client.init(args.force, args.remote_path)
    
    elif args.command == "sync":
        success = client.sync(not args.no_commit, args.verbose)
    
    elif args.command == "status":
        success = client.status(args.verbose)
    
    elif args.command == "resolve":
        success = client.resolve(args.strategy)
    
    elif args.command == "clean":
        success = client.clean()
    
    else:
        parser.print_help()
        return 1
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main()) 