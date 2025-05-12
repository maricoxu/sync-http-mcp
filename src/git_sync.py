#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sync-HTTP-MCP Git同步模块

基于Git diff/patch机制实现的增量同步。
"""

import os
import subprocess
import tempfile
import base64
import logging
import json
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple, Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class GitSyncManager:
    """Git同步管理器，处理基于Git的增量同步功能"""
    
    def __init__(self, local_path: str, remote_url: Optional[str] = None):
        """
        初始化Git同步管理器
        
        Args:
            local_path: 本地仓库路径
            remote_url: 远程同步服务器URL
        """
        self.local_path = Path(local_path).resolve()
        self.remote_url = remote_url
        self.last_sync_commit = None
        self.sync_marker = "SYNC-HTTP-MCP-POINT"
        
        # 确保本地路径存在
        os.makedirs(self.local_path, exist_ok=True)
    
    def init_repo(self) -> bool:
        """
        初始化Git仓库，如果已存在则跳过
        
        Returns:
            初始化是否成功
        """
        try:
            git_dir = self.local_path / ".git"
            
            if git_dir.exists():
                logger.info(f"Git仓库已存在于: {self.local_path}")
                return True
            
            # 初始化新仓库
            result = self._run_git_command(["init"])
            
            if result.returncode == 0:
                # 设置Git用户信息（如果尚未设置）
                if not self._is_git_user_configured():
                    self._run_git_command(["config", "user.name", "Sync-HTTP-MCP"])
                    self._run_git_command(["config", "user.email", "sync-mcp@example.com"])
                
                # 创建初始提交
                self._create_gitignore()
                self._run_git_command(["add", ".gitignore"])
                self._run_git_command(["commit", "-m", "Initial commit by Sync-HTTP-MCP"])
                
                # 创建初始同步点
                self.create_sync_point("Initial sync point")
                
                logger.info(f"Git仓库初始化成功: {self.local_path}")
                return True
            else:
                logger.error(f"Git仓库初始化失败: {result.stderr}")
                return False
        
        except Exception as e:
            logger.error(f"初始化Git仓库时出错: {str(e)}")
            return False
    
    def _is_git_user_configured(self) -> bool:
        """检查Git用户信息是否已配置"""
        try:
            name_result = self._run_git_command(["config", "user.name"])
            email_result = self._run_git_command(["config", "user.email"])
            
            return name_result.returncode == 0 and name_result.stdout.strip() and \
                   email_result.returncode == 0 and email_result.stdout.strip()
        except Exception:
            return False
    
    def _create_gitignore(self):
        """创建基本的.gitignore文件"""
        gitignore_content = """# Sync-HTTP-MCP gitignore
.DS_Store
__pycache__/
*.py[cod]
*$py.class
.env
.venv
env/
venv/
ENV/
.idea/
.vscode/
*.swp
*.swo
.mcp_cache.json
"""
        gitignore_path = self.local_path / ".gitignore"
        with open(gitignore_path, "w") as f:
            f.write(gitignore_content)
    
    def _run_git_command(self, args: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        """
        执行Git命令
        
        Args:
            args: Git命令参数
            cwd: 工作目录，默认为本地仓库路径
            
        Returns:
            命令执行结果
        """
        if cwd is None:
            cwd = str(self.local_path)
        
        # 构建完整命令
        cmd = ["git"] + args
        
        # 执行命令
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False  # 不自动抛出异常，我们会手动处理错误
        )
    
    def create_sync_point(self, message: str = "Sync point") -> Optional[str]:
        """
        创建同步点（commit）
        
        Args:
            message: 提交消息
            
        Returns:
            新创建的commit hash，失败则返回None
        """
        try:
            # 添加所有变更
            add_result = self._run_git_command(["add", "-A"])
            if add_result.returncode != 0:
                logger.error(f"添加文件失败: {add_result.stderr}")
                return None
            
            # 创建提交
            full_message = f"{message} [{self.sync_marker}]"
            commit_result = self._run_git_command(["commit", "-m", full_message])
            
            # 如果没有变更，也算成功（返回当前HEAD）
            if "nothing to commit" in commit_result.stdout or "nothing to commit" in commit_result.stderr:
                head_result = self._run_git_command(["rev-parse", "HEAD"])
                if head_result.returncode == 0:
                    commit_hash = head_result.stdout.strip()
                    self.last_sync_commit = commit_hash
                    logger.info(f"没有新变更，当前同步点: {commit_hash}")
                    return commit_hash
                return None
            
            # 获取新commit的hash
            if commit_result.returncode == 0:
                commit_hash = self._run_git_command(["rev-parse", "HEAD"]).stdout.strip()
                self.last_sync_commit = commit_hash
                logger.info(f"创建同步点成功: {commit_hash}")
                return commit_hash
            else:
                logger.error(f"创建提交失败: {commit_result.stderr}")
                return None
        
        except Exception as e:
            logger.error(f"创建同步点时出错: {str(e)}")
            return None
    
    def get_last_sync_point(self) -> Optional[str]:
        """
        获取最后一个同步点commit
        
        Returns:
            最后同步点的commit hash，如果没有则返回None
        """
        try:
            # 查找带有同步标记的最近提交
            result = self._run_git_command([
                "log", 
                "--grep", self.sync_marker, 
                "--format=%H", 
                "-n", "1"
            ])
            
            if result.returncode == 0 and result.stdout.strip():
                commit_hash = result.stdout.strip()
                self.last_sync_commit = commit_hash
                return commit_hash
            else:
                # 如果没找到同步点，返回第一个提交
                init_result = self._run_git_command([
                    "rev-list", "--max-parents=0", "HEAD"
                ])
                
                if init_result.returncode == 0 and init_result.stdout.strip():
                    commit_hash = init_result.stdout.strip()
                    self.last_sync_commit = commit_hash
                    return commit_hash
                
                return None
        
        except Exception as e:
            logger.error(f"获取最后同步点时出错: {str(e)}")
            return None
    
    def generate_patch(self, base_commit: Optional[str] = None) -> Optional[Dict]:
        """
        生成当前工作区相对于基准点的patch
        
        Args:
            base_commit: 基准commit，如果为None则使用最后一个同步点
            
        Returns:
            包含patch信息的字典，失败则返回None
        """
        try:
            # 如果没有指定基准点，获取最后的同步点
            if base_commit is None:
                base_commit = self.get_last_sync_point()
                if base_commit is None:
                    logger.error("无法找到基准同步点")
                    return None
            
            # 检查是否有未提交的变更
            status_result = self._run_git_command(["status", "--porcelain"])
            if status_result.returncode != 0:
                logger.error(f"获取状态失败: {status_result.stderr}")
                return None
            
            if not status_result.stdout.strip():
                logger.info("没有变更需要同步")
                return {
                    "status": "no_changes",
                    "base_commit": base_commit,
                    "patch_content": None,
                    "files_changed": 0
                }
            
            # 生成patch文件
            with tempfile.NamedTemporaryFile(suffix=".patch", delete=False) as temp_file:
                patch_path = temp_file.name
            
            # 包含工作区未提交变更的diff
            diff_result = self._run_git_command([
                "diff", 
                "--binary",  # 处理二进制文件
                base_commit, 
                "--output", patch_path
            ])
            
            # 加入未跟踪（新增）的文件
            untracked_files = []
            for line in status_result.stdout.splitlines():
                if line.startswith("??"):
                    file_path = line[3:].strip()
                    untracked_files.append(file_path)
            
            # 读取patch内容
            with open(patch_path, "rb") as f:
                patch_content = f.read()
            
            # 清理临时文件
            os.unlink(patch_path)
            
            # 计算变更的文件数
            files_changed_result = self._run_git_command([
                "diff", "--name-only", base_commit
            ])
            
            files_changed = len(files_changed_result.stdout.splitlines()) + len(untracked_files)
            
            # 将patch内容进行base64编码
            encoded_patch = base64.b64encode(patch_content).decode('utf-8')
            
            # 处理二进制文件
            binary_files = self._get_binary_files_content(untracked_files)
            
            return {
                "status": "success",
                "base_commit": base_commit,
                "patch_content": encoded_patch,
                "binary_files": binary_files,
                "untracked_files": untracked_files,
                "files_changed": files_changed
            }
        
        except Exception as e:
            logger.error(f"生成patch时出错: {str(e)}")
            return None
    
    def _get_binary_files_content(self, untracked_files: List[str]) -> List[Dict]:
        """获取未跟踪的二进制文件内容"""
        binary_files = []
        
        for file_path in untracked_files:
            full_path = self.local_path / file_path
            if full_path.exists() and full_path.is_file():
                # 检查是否为二进制文件
                is_binary = False
                try:
                    with open(full_path, 'r') as f:
                        f.read(1024)  # 尝试以文本方式读取
                except UnicodeDecodeError:
                    is_binary = True
                
                if is_binary:
                    with open(full_path, 'rb') as f:
                        content = f.read()
                    
                    binary_files.append({
                        "path": file_path,
                        "content": base64.b64encode(content).decode('utf-8')
                    })
        
        return binary_files
    
    def apply_patch(self, patch_content: str, binary_files: List[Dict] = None, 
                  base_commit: Optional[str] = None) -> Dict:
        """
        应用patch到仓库
        
        Args:
            patch_content: Base64编码的patch内容
            binary_files: 二进制文件列表
            base_commit: 基准commit，如果为None则使用最后一个同步点
            
        Returns:
            应用结果信息字典
        """
        try:
            # 如果没有指定基准点，获取最后的同步点
            if base_commit is None:
                base_commit = self.get_last_sync_point()
                if base_commit is None:
                    return {
                        "status": "error",
                        "message": "无法找到基准同步点"
                    }
            
            # 检查当前仓库状态
            status_result = self._run_git_command(["status", "--porcelain"])
            if status_result.stdout.strip():
                return {
                    "status": "error",
                    "message": "本地有未提交的变更，无法应用patch"
                }
            
            # 解码patch内容
            decoded_patch = base64.b64decode(patch_content)
            
            # 使用临时文件保存patch
            with tempfile.NamedTemporaryFile(suffix=".patch", delete=False) as temp_file:
                temp_file.write(decoded_patch)
                patch_path = temp_file.name
            
            try:
                # 先检查patch是否可以干净应用
                check_result = self._run_git_command([
                    "apply", "--check", patch_path
                ])
                
                if check_result.returncode != 0:
                    os.unlink(patch_path)
                    return {
                        "status": "conflict",
                        "message": f"Patch不能干净应用: {check_result.stderr}"
                    }
                
                # 应用patch
                apply_result = self._run_git_command([
                    "apply", patch_path
                ])
                
                if apply_result.returncode != 0:
                    return {
                        "status": "error",
                        "message": f"应用patch失败: {apply_result.stderr}"
                    }
                
                # 处理二进制文件
                if binary_files:
                    for binary_file in binary_files:
                        file_path = self.local_path / binary_file["path"]
                        file_dir = file_path.parent
                        
                        # 确保目录存在
                        os.makedirs(file_dir, exist_ok=True)
                        
                        # 写入文件内容
                        content = base64.b64decode(binary_file["content"])
                        with open(file_path, 'wb') as f:
                            f.write(content)
                
                # 创建同步点
                new_commit = self.create_sync_point("Applied remote changes")
                
                return {
                    "status": "success",
                    "message": "Patch已成功应用",
                    "new_commit": new_commit
                }
            
            finally:
                # 清理临时文件
                if os.path.exists(patch_path):
                    os.unlink(patch_path)
        
        except Exception as e:
            logger.error(f"应用patch时出错: {str(e)}")
            return {
                "status": "error",
                "message": f"应用patch时出错: {str(e)}"
            }
    
    def get_sync_status(self) -> Dict:
        """
        获取同步状态信息
        
        Returns:
            同步状态信息字典
        """
        try:
            # 获取最后同步点
            last_sync_commit = self.get_last_sync_point()
            
            if not last_sync_commit:
                return {
                    "status": "not_initialized",
                    "message": "未找到同步点，仓库可能未初始化"
                }
            
            # 获取最后同步点的时间
            time_result = self._run_git_command([
                "show", "-s", "--format=%ci", last_sync_commit
            ])
            
            last_sync_time = time_result.stdout.strip() if time_result.returncode == 0 else None
            
            # 检查是否有未提交变更
            status_result = self._run_git_command(["status", "--porcelain"])
            pending_changes = bool(status_result.stdout.strip())
            
            # 获取变更的文件列表
            changed_files = []
            if pending_changes:
                files_result = self._run_git_command([
                    "diff", "--name-status", last_sync_commit
                ])
                
                for line in files_result.stdout.splitlines():
                    if line.strip():
                        parts = line.split(maxsplit=1)
                        if len(parts) >= 2:
                            status, path = parts[0], parts[1]
                            changed_files.append({
                                "path": path,
                                "status": self._parse_git_status(status)
                            })
            
            # 获取未跟踪的文件
            untracked_files = []
            for line in status_result.stdout.splitlines():
                if line.startswith("??"):
                    file_path = line[3:].strip()
                    untracked_files.append(file_path)
            
            return {
                "status": "ready",
                "last_sync_commit": last_sync_commit,
                "last_sync_time": last_sync_time,
                "pending_changes": pending_changes,
                "changed_files": changed_files,
                "untracked_files": untracked_files,
                "total_changes": len(changed_files) + len(untracked_files)
            }
        
        except Exception as e:
            logger.error(f"获取同步状态时出错: {str(e)}")
            return {
                "status": "error",
                "message": f"获取同步状态时出错: {str(e)}"
            }
    
    def _parse_git_status(self, status_code: str) -> str:
        """解析Git状态码为可读状态"""
        status_map = {
            'M': 'modified',
            'A': 'added',
            'D': 'deleted',
            'R': 'renamed',
            'C': 'copied',
            'U': 'updated_but_unmerged'
        }
        
        return status_map.get(status_code, f'unknown({status_code})')


# 测试代码
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Git Sync测试工具")
    parser.add_argument("--repo", required=True, help="本地仓库路径")
    parser.add_argument("command", choices=["init", "status", "patch", "apply"], 
                       help="要执行的命令")
    parser.add_argument("--patch-file", help="patch文件路径(用于apply命令)")
    
    args = parser.parse_args()
    
    sync_manager = GitSyncManager(args.repo)
    
    if args.command == "init":
        # 初始化仓库
        result = sync_manager.init_repo()
        print(f"初始化结果: {'成功' if result else '失败'}")
    
    elif args.command == "status":
        # 获取同步状态
        status = sync_manager.get_sync_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
    
    elif args.command == "patch":
        # 生成patch
        patch_info = sync_manager.generate_patch()
        if patch_info:
            # 保存patch到文件
            if patch_info["patch_content"]:
                patch_file = f"changes_{int(time.time())}.patch"
                patch_data = base64.b64decode(patch_info["patch_content"])
                with open(patch_file, "wb") as f:
                    f.write(patch_data)
                
                print(f"Patch已保存到: {patch_file}")
                print(f"变更文件数: {patch_info['files_changed']}")
            else:
                print("没有变更需要同步")
        else:
            print("生成patch失败")
    
    elif args.command == "apply":
        # 应用patch
        if not args.patch_file:
            print("错误: 需要提供patch文件路径")
            sys.exit(1)
        
        with open(args.patch_file, "rb") as f:
            patch_content = base64.b64encode(f.read()).decode('utf-8')
        
        result = sync_manager.apply_patch(patch_content)
        print(json.dumps(result, indent=2, ensure_ascii=False)) 