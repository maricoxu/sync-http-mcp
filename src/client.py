#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sync-HTTP-MCP 简化客户端库

提供与远程HTTP服务器通信的功能，使用更基础的依赖。
"""

import base64
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

import requests
import websocket

# 尝试导入增量同步模块
try:
    from delta_sync import (
        MetadataCache, DeltaSyncCalculator, FileMetadata, 
        create_delta_payload, DEFAULT_BLOCK_SIZE
    )
    DELTA_SYNC_AVAILABLE = True
except ImportError:
    DELTA_SYNC_AVAILABLE = False

# 尝试导入Git增量同步模块
try:
    from git_sync import GitSyncManager
    GIT_SYNC_AVAILABLE = True
except ImportError:
    GIT_SYNC_AVAILABLE = False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SimplifiedMCPClient:
    """简化版MCP客户端主类，处理与远程服务器的所有通信"""
    
    def __init__(self, server_url: str, workspace_path: str, use_delta_sync: bool = True):
        """
        初始化MCP客户端
        
        Args:
            server_url: 远程服务器URL (例如 http://localhost:8081)
            workspace_path: 本地工作区路径
            use_delta_sync: 是否使用增量同步功能（如果可用）
        """
        self.server_url = server_url.rstrip("/")
        self.workspace_path = Path(workspace_path).resolve()
        self.session = requests.Session()
        self.ws_connection = None
        
        # 增量同步相关
        self.use_delta_sync = use_delta_sync and DELTA_SYNC_AVAILABLE
        if self.use_delta_sync:
            cache_file = self.workspace_path / ".mcp_cache.json"
            self.metadata_cache = MetadataCache(str(cache_file))
            self.delta_calculator = DeltaSyncCalculator(self.metadata_cache)
            logger.info("已启用增量同步功能")
        else:
            if use_delta_sync and not DELTA_SYNC_AVAILABLE:
                logger.warning("增量同步模块不可用，将使用完整传输")
            self.metadata_cache = None
            self.delta_calculator = None
        
        logger.info(f"MCP客户端初始化 - 服务器: {server_url}, 工作区: {workspace_path}")
    
    def post(self, endpoint: str, data: dict) -> dict:
        """
        向服务器发送POST请求
        
        Args:
            endpoint: API端点路径
            data: 要发送的JSON数据
            
        Returns:
            服务器响应的JSON数据
        """
        try:
            response = self.session.post(f"{self.server_url}{endpoint}", json=data)
            if response.status_code == 200:
                return response.json()
            else:
                error_text = response.text
                logger.error(f"POST请求失败: {response.status_code} - {error_text}")
                return {"status": "error", "message": error_text}
        except Exception as e:
            logger.error(f"POST请求错误: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get(self, endpoint: str, params: dict = None) -> dict:
        """
        向服务器发送GET请求
        
        Args:
            endpoint: API端点路径
            params: 查询参数
            
        Returns:
            服务器响应的JSON数据
        """
        try:
            response = self.session.get(f"{self.server_url}{endpoint}", params=params)
            if response.status_code == 200:
                return response.json()
            else:
                error_text = response.text
                logger.error(f"GET请求失败: {response.status_code} - {error_text}")
                return {"status": "error", "message": error_text}
        except Exception as e:
            logger.error(f"GET请求错误: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def connect(self):
        """建立与服务器的连接"""
        # 测试连接
        try:
            response = self.session.get(f"{self.server_url}/")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"服务器信息: {data}")
                
                # 检查服务器是否支持增量同步
                if self.use_delta_sync and not data.get("delta_sync_supported", False):
                    logger.warning("服务器不支持增量同步，将使用完整传输")
                    self.use_delta_sync = False
                
                return True
            else:
                logger.error(f"连接服务器失败: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"连接服务器错误: {str(e)}")
            return False
    
    def disconnect(self):
        """关闭与服务器的连接"""
        self.session.close()
        if self.ws_connection:
            self.ws_connection.close()
            self.ws_connection = None
        
        # 保存元数据缓存
        if self.use_delta_sync and self.metadata_cache:
            self.metadata_cache.save_cache()
        
        logger.info("已断开与服务器的连接")
    
    def list_files(self, remote_path: str) -> List[Dict]:
        """
        获取远程文件列表
        
        Args:
            remote_path: 远程服务器上的路径
            
        Returns:
            文件和目录列表
        """
        try:
            response = self.session.get(
                f"{self.server_url}/api/v1/files",
                params={"path": remote_path}
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("files", [])
            else:
                error_text = response.text
                logger.error(f"获取文件列表失败: {response.status_code} - {error_text}")
                return []
        except Exception as e:
            logger.error(f"获取文件列表错误: {str(e)}")
            return []
    
    def get_file_content(self, remote_path: str) -> Optional[bytes]:
        """
        获取远程文件内容
        
        Args:
            remote_path: 远程服务器上的文件路径
            
        Returns:
            文件内容字节数据，如果失败则返回None
        """
        try:
            response = self.session.get(
                f"{self.server_url}/api/v1/files/content",
                params={"path": remote_path}
            )
            if response.status_code == 200:
                data = response.json()
                encoded_content = data.get("content", "")
                
                # 如果使用增量同步，更新远程元数据
                if self.use_delta_sync and self.metadata_cache and "metadata" in data:
                    try:
                        metadata = FileMetadata.from_dict(data["metadata"])
                        self.metadata_cache.update_remote_metadata(metadata)
                    except Exception as e:
                        logger.error(f"更新远程元数据失败: {str(e)}")
                
                return base64.b64decode(encoded_content)
            else:
                error_text = response.text
                logger.error(f"获取文件内容失败: {response.status_code} - {error_text}")
                return None
        except Exception as e:
            logger.error(f"获取文件内容错误: {str(e)}")
            return None
    
    def update_file_content(self, remote_path: str, content: bytes) -> bool:
        """
        更新远程文件内容
        
        Args:
            remote_path: 远程服务器上的文件路径
            content: 文件内容字节数据
            
        Returns:
            操作是否成功
        """
        try:
            # 计算MD5校验和
            checksum = hashlib.md5(content).hexdigest()
            
            # 常规方式：Base64编码整个内容
            if not self.use_delta_sync:
                encoded_content = base64.b64encode(content).decode('utf-8')
                
                payload = {
                    "path": remote_path,
                    "content": encoded_content,
                    "checksum": checksum
                }
                
                response = self.session.put(
                    f"{self.server_url}/api/v1/files/content",
                    json=payload
                )
            else:
                # 使用增量同步方式
                # 创建临时文件存储内容，以便计算增量
                temp_file = None
                try:
                    # 使用临时文件计算增量
                    import tempfile
                    fd, temp_file = tempfile.mkstemp(prefix="mcp_delta_")
                    os.close(fd)
                    
                    with open(temp_file, "wb") as f:
                        f.write(content)
                    
                    # 计算增量并创建负载
                    delta_info = self.delta_calculator.calculate_delta(temp_file, remote_path)
                    payload = create_delta_payload(temp_file, remote_path, delta_info)
                    
                    # 发送增量更新请求
                    response = self.session.put(
                        f"{self.server_url}/api/v1/files/delta",
                        json=payload
                    )
                    
                    # 如果服务器不支持增量更新，回退到完整传输
                    if response.status_code == 404:
                        logger.warning("服务器不支持增量更新API，回退到完整传输")
                        self.use_delta_sync = False
                        
                        # 回退到常规更新
                        encoded_content = base64.b64encode(content).decode('utf-8')
                        payload = {
                            "path": remote_path,
                            "content": encoded_content,
                            "checksum": checksum
                        }
                        
                        response = self.session.put(
                            f"{self.server_url}/api/v1/files/content",
                            json=payload
                        )
                finally:
                    # 清理临时文件
                    if temp_file and os.path.exists(temp_file):
                        os.unlink(temp_file)
            
            # 处理响应
            if response.status_code == 200:
                data = response.json()
                
                # 如果使用增量同步，更新远程元数据
                if self.use_delta_sync and self.metadata_cache and "metadata" in data:
                    try:
                        metadata = FileMetadata.from_dict(data["metadata"])
                        self.metadata_cache.update_remote_metadata(metadata)
                        self.metadata_cache.save_cache()
                    except Exception as e:
                        logger.error(f"更新远程元数据失败: {str(e)}")
                
                logger.info(f"文件更新成功: {remote_path}")
                return True
            else:
                error_text = response.text
                logger.error(f"更新文件内容失败: {response.status_code} - {error_text}")
                return False
        except Exception as e:
            logger.error(f"更新文件内容错误: {str(e)}")
            return False
    
    def sync_files(self, file_changes: List[Dict]) -> Dict:
        """
        批量同步文件
        
        Args:
            file_changes: 文件变更列表，包含path和content
            
        Returns:
            同步结果信息
        """
        try:
            # 准备请求数据
            files = []
            
            # 对每个文件处理
            for file_info in file_changes:
                remote_path = file_info["path"]
                content = file_info.get("content", b"")
                
                # 如果不使用增量同步或内容不是字节类型，进行常规处理
                if not self.use_delta_sync or not isinstance(content, bytes):
                    if isinstance(content, bytes):
                        encoded_content = base64.b64encode(content).decode('utf-8')
                        checksum = hashlib.md5(content).hexdigest()
                    else:
                        encoded_content = content
                        checksum = None
                    
                    files.append({
                        "path": remote_path,
                        "content": encoded_content,
                        "checksum": checksum,
                        "delta_type": "full"
                    })
                else:
                    # 使用增量同步，需要创建临时文件
                    temp_file = None
                    try:
                        import tempfile
                        fd, temp_file = tempfile.mkstemp(prefix="mcp_delta_")
                        os.close(fd)
                        
                        with open(temp_file, "wb") as f:
                            f.write(content)
                        
                        # 计算增量
                        delta_info = self.delta_calculator.calculate_delta(temp_file, remote_path)
                        
                        # 如果不需要传输，跳过
                        if delta_info["type"] == "none":
                            continue
                        
                        # 创建增量负载
                        payload = create_delta_payload(temp_file, remote_path, delta_info)
                        files.append(payload)
                    finally:
                        # 清理临时文件
                        if temp_file and os.path.exists(temp_file):
                            os.unlink(temp_file)
            
            # 如果没有需要同步的文件，直接返回成功
            if not files:
                logger.info("所有文件都是最新的，无需同步")
                return {"status": "success", "synchronized": 0, "failed": 0}
            
            # 发送批量同步请求
            endpoint = "/api/v1/files/delta_sync" if self.use_delta_sync else "/api/v1/files/sync"
            payload = {"files": files}
            
            response = self.session.post(
                f"{self.server_url}{endpoint}",
                json=payload
            )
            
            # 如果增量同步API不可用，回退到常规同步
            if self.use_delta_sync and response.status_code == 404:
                logger.warning("服务器不支持增量同步API，回退到常规同步")
                self.use_delta_sync = False
                
                # 重新准备常规同步数据
                regular_files = []
                for file_info in file_changes:
                    content = file_info.get("content", b"")
                    if isinstance(content, bytes):
                        encoded_content = base64.b64encode(content).decode('utf-8')
                        checksum = hashlib.md5(content).hexdigest()
                    else:
                        encoded_content = content
                        checksum = None
                    
                    regular_files.append({
                        "path": file_info["path"],
                        "content": encoded_content,
                        "checksum": checksum
                    })
                
                payload = {"files": regular_files}
                response = self.session.post(
                    f"{self.server_url}/api/v1/files/sync",
                    json=payload
                )
            
            if response.status_code == 200:
                data = response.json()
                
                # 如果使用增量同步并且服务器返回了元数据，更新远程元数据缓存
                if self.use_delta_sync and self.metadata_cache and "metadata" in data:
                    for path, meta_dict in data["metadata"].items():
                        try:
                            metadata = FileMetadata.from_dict(meta_dict)
                            self.metadata_cache.update_remote_metadata(metadata)
                        except Exception as e:
                            logger.error(f"更新远程元数据失败: {path} - {str(e)}")
                    
                    self.metadata_cache.save_cache()
                
                logger.info(f"文件同步成功: {data.get('synchronized', 0)}个文件")
                return data
            else:
                error_text = response.text
                logger.error(f"批量同步文件失败: {response.status_code} - {error_text}")
                return {"status": "error", "synchronized": 0, "failed": len(files)}
        except Exception as e:
            logger.error(f"批量同步文件错误: {str(e)}")
            return {"status": "error", "synchronized": 0, "failed": len(file_changes)}
    
    def execute_command(self, command: str, working_dir: str, 
                       env: Optional[Dict[str, str]] = None,
                       timeout: int = 300) -> Dict:
        """
        在远程服务器上执行命令
        
        Args:
            command: 要执行的命令
            working_dir: 命令执行的工作目录
            env: 环境变量
            timeout: 超时时间(秒)
            
        Returns:
            命令执行结果信息
        """
        try:
            payload = {
                "command": command,
                "working_directory": working_dir,
                "environment": env or {},
                "timeout": timeout
            }
            
            response = self.session.post(
                f"{self.server_url}/api/v1/commands",
                json=payload
            )
            if response.status_code == 200:
                data = response.json()
                logger.info(f"命令执行已提交: {command}")
                return data
            else:
                error_text = response.text
                logger.error(f"执行命令失败: {response.status_code} - {error_text}")
                return {"status": "error"}
        except Exception as e:
            logger.error(f"执行命令错误: {str(e)}")
            return {"status": "error"}
    
    def get_command_status(self, command_id: str) -> Dict:
        """
        获取命令执行状态
        
        Args:
            command_id: 命令ID
            
        Returns:
            命令状态信息
        """
        try:
            response = self.session.get(
                f"{self.server_url}/api/v1/commands/{command_id}"
            )
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                error_text = response.text
                logger.error(f"获取命令状态失败: {response.status_code} - {error_text}")
                return {"status": "unknown"}
        except Exception as e:
            logger.error(f"获取命令状态错误: {str(e)}")
            return {"status": "unknown"}
    
    def get_command_output(self, command_id: str) -> Dict:
        """
        获取命令执行输出
        
        Args:
            command_id: 命令ID
            
        Returns:
            命令输出信息
        """
        try:
            response = self.session.get(
                f"{self.server_url}/api/v1/commands/{command_id}/output"
            )
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                error_text = response.text
                logger.error(f"获取命令输出失败: {response.status_code} - {error_text}")
                return {"output": "", "is_complete": True}
        except Exception as e:
            logger.error(f"获取命令输出错误: {str(e)}")
            return {"output": "", "is_complete": True}
    
    def connect_websocket(self, callback_function):
        """
        连接WebSocket获取实时通知
        
        Args:
            callback_function: 消息处理回调函数
        """
        ws_url = f"{self.server_url.replace('http', 'ws')}/ws"
        try:
            def on_message(ws, message):
                data = json.loads(message)
                callback_function(data)
            
            def on_error(ws, error):
                logger.error(f"WebSocket错误: {error}")
            
            def on_close(ws, close_status_code, close_msg):
                logger.warning("WebSocket连接已关闭")
            
            def on_open(ws):
                logger.info(f"WebSocket连接已建立: {ws_url}")
            
            self.ws_connection = websocket.WebSocketApp(ws_url,
                                                     on_message=on_message,
                                                     on_error=on_error,
                                                     on_close=on_close,
                                                     on_open=on_open)
            
            # 运行WebSocket连接 (阻塞调用)
            self.ws_connection.run_forever()
        except Exception as e:
            logger.error(f"建立WebSocket连接错误: {str(e)}")
    
    def sync_local_to_remote(self, local_path: str, remote_path: str, 
                            recursive: bool = True) -> Dict:
        """
        将本地目录或文件同步到远程
        
        Args:
            local_path: 本地路径
            remote_path: 远程路径
            recursive: 是否递归同步子目录
            
        Returns:
            同步结果信息
        """
        local_full_path = Path(local_path).resolve()
        if not local_full_path.exists():
            logger.error(f"本地路径不存在: {local_path}")
            return {"status": "error", "message": "本地路径不存在"}
        
        if local_full_path.is_file():
            # 同步单个文件
            try:
                with open(local_full_path, "rb") as f:
                    content = f.read()
                
                result = self.update_file_content(remote_path, content)
                return {
                    "status": "success" if result else "error",
                    "synchronized": 1 if result else 0,
                    "failed": 0 if result else 1
                }
            except Exception as e:
                logger.error(f"同步文件错误: {str(e)}")
                return {"status": "error", "synchronized": 0, "failed": 1}
        elif local_full_path.is_dir() and recursive:
            # 递归同步目录
            file_changes = []
            total_files = 0
            
            for root, dirs, files in os.walk(local_full_path):
                for file in files:
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(local_full_path)
                    remote_file_path = f"{remote_path}/{rel_path}"
                    total_files += 1
                    
                    try:
                        with open(file_path, "rb") as f:
                            content = f.read()
                        
                        file_changes.append({
                            "path": remote_file_path,
                            "content": content
                        })
                    except Exception as e:
                        logger.error(f"读取文件错误: {file_path} - {str(e)}")
            
            if file_changes:
                logger.info(f"准备同步{len(file_changes)}/{total_files}个文件")
                return self.sync_files(file_changes)
            else:
                return {"status": "success", "synchronized": 0, "failed": 0}
        else:
            return {"status": "error", "message": "不支持的路径类型或参数"}


# 兼容性别名，用于支持旧的调用方式
Client = SimplifiedMCPClient


def main():
    """命令行入口点"""
    import argparse
    import os
    
    # 默认参数
    DEFAULT_SERVER = "http://localhost:8081"
    DEFAULT_WORKSPACE = os.getcwd()
    
    parser = argparse.ArgumentParser(description="简化版MCP客户端")
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER, 
                      help=f"远程服务器URL (默认: {DEFAULT_SERVER})")
    parser.add_argument("--workspace", "-w", default=DEFAULT_WORKSPACE, 
                      help=f"本地工作区路径 (默认: 当前目录)")
    parser.add_argument("--command", "-c", help="要执行的命令")
    parser.add_argument("--dir", "-d", help="命令执行目录 (默认: /home)")
    parser.add_argument("--no-delta", action="store_true", help="禁用增量同步功能")
    parser.add_argument("--sync-mode", choices=["block", "git"], default="git",
                      help="同步模式：block (块级增量同步) 或 git (Git增量同步)，默认为git")
    parser.add_argument("--block", action="store_true", 
                      help="使用块级增量同步（覆盖--sync-mode设置）")
    
    subparsers = parser.add_subparsers(dest="action", help="操作")
    
    # 列出文件子命令
    list_parser = subparsers.add_parser("list", help="列出远程文件")
    list_parser.add_argument("path", nargs="?", default="/home", help="远程路径 (默认: /home)")
    
    # 获取文件内容子命令
    get_parser = subparsers.add_parser("get", help="获取文件内容")
    get_parser.add_argument("path", help="远程文件路径")
    get_parser.add_argument("--output", "-o", help="输出文件路径")
    
    # 上传文件子命令
    put_parser = subparsers.add_parser("put", help="上传文件")
    put_parser.add_argument("local_path", help="本地文件路径")
    put_parser.add_argument("remote_path", nargs="?", help="远程文件路径 (默认: 与本地文件同名)")
    
    # 同步目录子命令
    sync_parser = subparsers.add_parser("sync", help="同步目录")
    sync_parser.add_argument("local_path", nargs="?", default=".", help="本地目录路径 (默认: 当前目录)")
    sync_parser.add_argument("remote_path", nargs="?", default="/home", help="远程目录路径 (默认: /home)")
    sync_parser.add_argument("--git", action="store_true", help="使用Git增量同步（覆盖全局设置）")
    sync_parser.add_argument("--block", action="store_true", help="使用块级增量同步（覆盖全局设置）")
    
    # Git同步相关命令
    if GIT_SYNC_AVAILABLE:
        # git-init命令
        git_init_parser = subparsers.add_parser("git-init", help="初始化Git同步环境")
        git_init_parser.add_argument("--force", "-f", action="store_true", help="强制初始化")
        git_init_parser.add_argument("--remote-path", help="服务器上的远程目录路径（默认: 与本地工作区同名）")
        
        # git-status命令
        git_status_parser = subparsers.add_parser("git-status", help="显示Git同步状态")
        git_status_parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
        
        # git-resolve命令
        git_resolve_parser = subparsers.add_parser("git-resolve", help="解决Git同步冲突")
        git_resolve_parser.add_argument("--strategy", choices=["local", "remote", "interactive"], 
                                      default="interactive", help="冲突解决策略")
    
    # 清理缓存子命令
    clean_parser = subparsers.add_parser("clean", help="清理元数据缓存")
    clean_parser.add_argument("--local", help="本地基础路径，用于清理相关缓存")
    clean_parser.add_argument("--remote", help="远程基础路径，用于清理相关缓存")
    
    args = parser.parse_args()
    
    # 处理默认参数
    if args.action == "put" and not args.remote_path:
        local_path = Path(args.local_path)
        args.remote_path = f"/home/{local_path.name}"
        print(f"未指定远程路径，使用默认值: {args.remote_path}")
    
    if args.command and not args.dir:
        args.dir = "/home"
        print(f"未指定工作目录，使用默认值: {args.dir}")
    
    print(f"连接到服务器: {args.server}")
    print(f"本地工作区: {args.workspace}")
    
    # 检查是否使用Git同步模式
    use_git_sync = True  # 默认使用Git同步
    
    # 如果全局或命令级别指定了块级同步，则使用块级同步
    if args.block or (args.action == "sync" and args.block):
        use_git_sync = False
        print("使用块级增量同步模式")
    elif args.sync_mode == "block":
        use_git_sync = False
        print("使用块级增量同步模式")
    else:
        # 默认或明确指定使用Git同步
        if GIT_SYNC_AVAILABLE:
            print("使用Git增量同步模式")
        else:
            print("警告: Git增量同步模块不可用，将使用块级增量同步")
            use_git_sync = False
    
    if use_git_sync:
        from client_commands import GitSyncClient
        client = GitSyncClient(args.workspace, args.server)
        
        try:
            if args.action == "sync":
                success = client.sync(auto_commit=True, verbose=True)
                if not success:
                    print("Git同步失败，尝试使用块级同步API作为后备")
                    # 回退到块级同步
                    standard_client = SimplifiedMCPClient(args.server, args.workspace, use_delta_sync=True)
                    connect_result = standard_client.connect()
                    if connect_result:
                        print("使用块级同步API传输文件...")
                        result = standard_client.sync_local_to_remote(args.local_path if hasattr(args, 'local_path') and args.local_path else ".", 
                                                               args.remote_path if hasattr(args, 'remote_path') and args.remote_path else "/home")
                        print(f"同步结果: {result['status']}")
                        print(f"成功: {result.get('synchronized', 0)} 个文件")
                        print(f"失败: {result.get('failed', 0)} 个文件")
                        standard_client.disconnect()
                    else:
                        print("错误: 无法连接到服务器")
                        sys.exit(1)
                    
            elif args.action == "git-init":
                remote_path = args.remote_path if hasattr(args, 'remote_path') and args.remote_path else None
                success = client.init(force=args.force if hasattr(args, 'force') else False, remote_path=remote_path)
                if not success:
                    print("Git初始化失败，尝试使用标准API创建远程目录")
                    # 回退到块级同步API创建目录
                    standard_client = SimplifiedMCPClient(args.server, args.workspace, use_delta_sync=True)
                    connect_result = standard_client.connect()
                    if connect_result:
                        # 尝试创建远程目录
                        path = remote_path if remote_path else os.path.basename(args.workspace)
                        print(f"尝试创建远程目录: {path}")
                        
                        # 使用list API检查目录是否存在
                        files = standard_client.list_files(os.path.dirname(path))
                        directory_exists = False
                        for item in files:
                            if item["type"] == "directory" and item["path"] == path:
                                directory_exists = True
                                break
                        
                        if directory_exists:
                            print(f"远程目录已存在: {path}")
                            sys.exit(0)
                        else:
                            # 目录不存在，创建一个空文件夹标识文件
                            folder_marker = f"{path}/.folder"
                            result = standard_client.update_file_content(folder_marker, b"")
                            if result:
                                print(f"已创建远程目录标识: {path}")
                                sys.exit(0)
                            else:
                                print(f"无法创建远程目录标识: {path}")
                                sys.exit(1)
                    else:
                        print("错误: 无法连接到服务器")
                        sys.exit(1)
                    
            elif args.action == "git-status":
                success = client.status(verbose=args.verbose if hasattr(args, 'verbose') else False)
                if not success:
                    sys.exit(1)
            elif args.action == "git-resolve":
                success = client.resolve(strategy=args.strategy if hasattr(args, 'strategy') else "interactive")
                if not success:
                    sys.exit(1)
            else:
                print("使用Git同步模式时，只支持sync、git-init、git-status和git-resolve命令")
                sys.exit(1)
        except Exception as e:
            print(f"执行Git同步操作时出错: {str(e)}")
            print("尝试使用块级同步API替代...")
            # 回退到块级同步
            use_git_sync = False
            
        if not use_git_sync:
            # 如果已成功执行Git同步操作，则退出
            sys.exit(0)
    
    # 创建普通客户端实例
    use_delta_sync = not args.no_delta
    client = SimplifiedMCPClient(args.server, args.workspace, use_delta_sync)
    connect_result = client.connect()
    
    if not connect_result:
        print("错误: 无法连接到服务器，请检查服务器地址和网络连接")
        sys.exit(1)
    
    try:
        if args.action == "list":
            files = client.list_files(args.path)
            if not files:
                print(f"目录为空或不存在: {args.path}")
            for item in files:
                file_type = "[DIR]" if item["type"] == "directory" else "[FILE]"
                print(f"{file_type} {item['path']}")
        
        elif args.action == "get":
            content = client.get_file_content(args.path)
            if content:
                if args.output:
                    with open(args.output, "wb") as f:
                        f.write(content)
                    print(f"文件已保存到: {args.output}")
                else:
                    # 尝试以文本方式打印内容
                    try:
                        print(content.decode('utf-8'))
                    except UnicodeDecodeError:
                        print("[二进制内容，无法显示]")
            else:
                print("获取文件内容失败")
        
        elif args.action == "put":
            local_path = Path(args.local_path)
            if not local_path.exists():
                print(f"错误: 本地文件不存在: {local_path}")
                return
            
            start_time = time.time()
            original_size = os.path.getsize(local_path)
            
            with open(local_path, "rb") as f:
                content = f.read()
            
            result = client.update_file_content(args.remote_path, content)
            end_time = time.time()
            
            if result:
                duration = end_time - start_time
                speed = original_size / duration / 1024 if duration > 0 else 0
                print(f"文件已上传: {args.remote_path}")
                print(f"大小: {original_size/1024:.2f} KB, 耗时: {duration:.2f} 秒, 速度: {speed:.2f} KB/s")
            else:
                print("上传文件失败")
        
        elif args.action == "sync":
            start_time = time.time()
            print(f"同步目录: {args.local_path} -> {args.remote_path}")
            result = client.sync_local_to_remote(args.local_path, args.remote_path)
            end_time = time.time()
            
            print(f"同步结果: {result['status']}")
            print(f"成功: {result.get('synchronized', 0)} 个文件")
            print(f"失败: {result.get('failed', 0)} 个文件")
            print(f"耗时: {end_time - start_time:.2f} 秒")
        
        elif args.action == "clean":
            if not client.use_delta_sync:
                print("增量同步功能未启用，无需清理缓存")
                return
            
            count = client.metadata_cache.clean_up(args.local, args.remote)
            client.metadata_cache.save_cache()
            print(f"缓存清理完成，移除了 {count} 个过期项")
        
        elif args.command:
            print(f"执行命令: {args.command}")
            print(f"工作目录: {args.dir}")
            result = client.execute_command(args.command, args.dir)
            command_id = result.get("command_id")
            if not command_id:
                print("执行命令失败")
                return
            
            print(f"命令ID: {command_id}, 状态: {result.get('status')}")
            
            # 轮询命令状态和输出
            last_output_length = 0
            while True:
                status = client.get_command_status(command_id)
                if status.get("status") in ["completed", "failed", "timeout"]:
                    output = client.get_command_output(command_id)
                    print(output.get("output", ""))
                    print(f"命令执行完成，状态: {status.get('status')}")
                    print(f"退出码: {status.get('exit_code')}")
                    break
                
                # 获取当前输出
                output = client.get_command_output(command_id)
                current_output = output.get("output", "")
                if len(current_output) > last_output_length:
                    print(current_output[last_output_length:], end="", flush=True)
                    last_output_length = len(current_output)
                
                time.sleep(1)
        
        else:
            parser.print_help()
    
    finally:
        client.disconnect()


if __name__ == "__main__":
    main() 