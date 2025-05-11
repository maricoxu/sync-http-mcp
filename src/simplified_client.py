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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SimplifiedMCPClient:
    """简化版MCP客户端主类，处理与远程服务器的所有通信"""
    
    def __init__(self, server_url: str, workspace_path: str):
        """
        初始化MCP客户端
        
        Args:
            server_url: 远程服务器URL (例如 http://localhost:8081)
            workspace_path: 本地工作区路径
        """
        self.server_url = server_url.rstrip("/")
        self.workspace_path = Path(workspace_path).resolve()
        self.session = requests.Session()
        self.ws_connection = None
        logger.info(f"MCP客户端初始化 - 服务器: {server_url}, 工作区: {workspace_path}")
    
    def connect(self):
        """建立与服务器的连接"""
        # 测试连接
        try:
            response = self.session.get(f"{self.server_url}/")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"服务器信息: {data}")
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
            
            # Base64编码内容
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
            if response.status_code == 200:
                data = response.json()
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
            for file_info in file_changes:
                content = file_info.get("content", b"")
                if isinstance(content, bytes):
                    encoded_content = base64.b64encode(content).decode('utf-8')
                    checksum = hashlib.md5(content).hexdigest()
                else:
                    encoded_content = content
                    checksum = None
                
                files.append({
                    "path": file_info["path"],
                    "content": encoded_content,
                    "checksum": checksum
                })
            
            payload = {"files": files}
            
            response = self.session.post(
                f"{self.server_url}/api/v1/files/sync",
                json=payload
            )
            if response.status_code == 200:
                data = response.json()
                logger.info(f"文件同步成功: {len(files)}个文件")
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
            for root, dirs, files in os.walk(local_full_path):
                for file in files:
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(local_full_path)
                    remote_file_path = f"{remote_path}/{rel_path}"
                    
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
                return self.sync_files(file_changes)
            else:
                return {"status": "success", "synchronized": 0, "failed": 0}
        else:
            return {"status": "error", "message": "不支持的路径类型或参数"}


# 命令行功能
def main():
    """命令行入口点"""
    import argparse
    
    parser = argparse.ArgumentParser(description="简化版MCP客户端")
    parser.add_argument("--server", "-s", required=True, help="远程服务器URL")
    parser.add_argument("--workspace", "-w", required=True, help="本地工作区路径")
    parser.add_argument("--command", "-c", help="要执行的命令")
    parser.add_argument("--dir", "-d", help="命令执行目录")
    
    subparsers = parser.add_subparsers(dest="action", help="操作")
    
    # 列出文件子命令
    list_parser = subparsers.add_parser("list", help="列出远程文件")
    list_parser.add_argument("path", help="远程路径")
    
    # 获取文件内容子命令
    get_parser = subparsers.add_parser("get", help="获取文件内容")
    get_parser.add_argument("path", help="远程文件路径")
    get_parser.add_argument("--output", "-o", help="输出文件路径")
    
    # 上传文件子命令
    put_parser = subparsers.add_parser("put", help="上传文件")
    put_parser.add_argument("local_path", help="本地文件路径")
    put_parser.add_argument("remote_path", help="远程文件路径")
    
    # 同步目录子命令
    sync_parser = subparsers.add_parser("sync", help="同步目录")
    sync_parser.add_argument("local_path", help="本地目录路径")
    sync_parser.add_argument("remote_path", help="远程目录路径")
    
    args = parser.parse_args()
    
    # 创建客户端实例
    client = SimplifiedMCPClient(args.server, args.workspace)
    client.connect()
    
    try:
        if args.action == "list":
            files = client.list_files(args.path)
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
            
            with open(local_path, "rb") as f:
                content = f.read()
            
            result = client.update_file_content(args.remote_path, content)
            if result:
                print(f"文件已上传: {args.remote_path}")
            else:
                print("上传文件失败")
        
        elif args.action == "sync":
            result = client.sync_local_to_remote(args.local_path, args.remote_path)
            print(f"同步结果: {result['status']}")
            print(f"成功: {result.get('synchronized', 0)} 个文件")
            print(f"失败: {result.get('failed', 0)} 个文件")
        
        elif args.command:
            if not args.dir:
                print("错误: 执行命令需要指定工作目录 (--dir)")
                return
            
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
            print("未指定操作，请使用 --help 查看帮助")
    
    finally:
        client.disconnect()


if __name__ == "__main__":
    main() 