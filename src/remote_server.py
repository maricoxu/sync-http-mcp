#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sync-HTTP-MCP Remote Server

这是远程HTTP服务器的主要实现，部署在百度内网服务器上，
提供文件访问和命令执行等API。
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import uuid
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Tuple

# 尝试导入GitPython库，如果不可用则设置标志
try:
    import git
    from git import Repo, GitCommandError
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False

# 尝试导入Git文件状态管理
try:
    from git_file_state import GitStateManager, GitFileState
    GIT_STATE_AVAILABLE = True
except ImportError:
    GIT_STATE_AVAILABLE = False

import aiofiles
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="Sync-HTTP-MCP Remote Server",
    description="百度内网远程开发服务器",
    version="0.2.0",
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该限制为特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 程序配置
SERVER_CONFIG = {
    "test_mode": False,  # 是否为本地测试模式
    "test_root_dir": str(Path.home() / "mcp_test_root"),  # 测试模式下的虚拟根目录，默认为用户主目录下的mcp_test_root
    "cache_dir": "~/.mcp_cache",  # Git状态缓存目录
    "git_cache_enabled": True,  # 是否启用Git状态缓存
}

# 全局状态管理
GIT_STATE_MANAGERS = {}  # 路径 -> GitStateManager 实例

# 通用路径映射函数
def map_remote_path(path: str) -> str:
    """
    将远程路径映射到本地路径
    
    Args:
        path: 原始路径
        
    Returns:
        映射后的路径
    """
    # 在测试模式下进行路径映射
    if SERVER_CONFIG["test_mode"] and path and path.startswith("/home/"):
        mapped_path = os.path.join(SERVER_CONFIG["test_root_dir"], path[1:])
        logger.info(f"测试模式路径映射: 将 {path} 映射到 {mapped_path}")
        return mapped_path
    
    # 在真实服务器环境中，直接使用原始路径
    # 当前服务器可能运行在Linux环境，有/home目录
    return path

# 数据模型
class FileInfo(BaseModel):
    """文件信息模型"""
    name: str
    path: str
    type: str  # "file" or "directory"
    size: Optional[int] = None
    last_modified: Optional[str] = None


class FileContent(BaseModel):
    """文件内容模型"""
    path: str
    content: str  # base64 encoded
    checksum: Optional[str] = None


class FileContentResponse(BaseModel):
    """文件内容响应模型"""
    content: str  # base64 encoded
    path: str
    last_modified: str
    checksum: str


class FileSyncRequest(BaseModel):
    """文件同步请求模型"""
    files: List[FileContent]


class FileSyncResponse(BaseModel):
    """文件同步响应模型"""
    status: str
    synchronized: int
    failed: int
    details: List[Dict[str, str]]


# 增量同步相关模型
class FileMetadata(BaseModel):
    """文件元数据模型"""
    path: str
    mtime: float
    size: int
    full_hash: str
    blocks: Dict[str, str]  # 块索引 -> 哈希值


class DeltaContent(BaseModel):
    """增量同步内容模型"""
    path: str
    delta_type: str  # "full", "delta", "none"
    full_hash: str
    size: int
    blocks: Optional[Dict[str, str]] = None  # 块索引 -> base64编码内容
    content: Optional[str] = None  # 完整内容(base64编码)


class DeltaSyncRequest(BaseModel):
    """增量同步请求模型"""
    files: List[DeltaContent]


class DeltaSyncResponse(BaseModel):
    """增量同步响应模型"""
    status: str
    synchronized: int
    failed: int
    details: List[Dict[str, str]]
    metadata: Dict[str, Any] = {}


class CommandRequest(BaseModel):
    """命令执行请求模型"""
    command: str
    working_directory: str
    environment: Optional[Dict[str, str]] = None
    timeout: Optional[int] = 300


class CommandResponse(BaseModel):
    """命令执行响应模型"""
    command_id: str
    status: str
    start_time: str


class CommandStatus(BaseModel):
    """命令状态模型"""
    command_id: str
    status: str
    start_time: str
    end_time: Optional[str] = None
    exit_code: Optional[int] = None
    output_url: str


class CommandOutput(BaseModel):
    """命令输出模型"""
    output: str
    is_complete: bool


# Git同步相关模型
class GitInitRequest(BaseModel):
    """Git仓库初始化请求模型"""
    path: str
    force: bool = False


class GitPatchRequest(BaseModel):
    """Git补丁请求模型"""
    base_commit: str
    patch_content: str
    binary_files: List[Dict[str, str]] = []  # 格式：[{"path": "文件路径", "content": "base64编码内容"}]


class GitConflictFile(BaseModel):
    """Git冲突文件模型"""
    path: str
    local_content: Optional[str] = None  # base64编码
    remote_content: Optional[str] = None  # base64编码
    merged_content: Optional[str] = None  # base64编码


class GitConflictResolution(BaseModel):
    """Git冲突解决模型"""
    path: str
    resolution: str  # "local", "remote", "merged"
    content: Optional[str] = None  # 如果是"merged"，这里是base64编码的合并内容


class GitConflictResolutionRequest(BaseModel):
    """Git冲突解决请求模型"""
    conflicts: List[GitConflictResolution]


# 应用状态
active_commands = {}  # command_id -> command_info
file_metadata_cache = {}  # file_path -> metadata
git_sync_info = {}  # path -> {"repo": repo_object, "last_sync": timestamp, "last_commit": commit_hash}
conflict_files = {}  # path -> GitConflictFile列表


# Git相关函数
def is_git_available():
    """检查是否可以使用Git功能"""
    return GIT_AVAILABLE


def init_git_repo(path: str, force: bool = False) -> Dict[str, Any]:
    """
    初始化Git仓库
    
    Args:
        path: 仓库路径
        force: 是否强制初始化（如果已存在）
        
    Returns:
        操作结果信息
    """
    # 路径映射
    path = map_remote_path(path)
    repo_path = Path(path)
    
    # 检查Git是否可用
    if not GIT_AVAILABLE:
        return {
            "status": "error",
            "message": "Git功能不可用，请安装GitPython库"
        }
    
    try:
        # 检查目录是否存在，不存在则创建
        repo_path.mkdir(parents=True, exist_ok=True)
        
        # 检查是否已经是Git仓库
        if (repo_path / ".git").exists() and not force:
            # 获取状态管理器
            if GIT_STATE_AVAILABLE:
                state_manager = get_or_create_state_manager(str(repo_path))
                if state_manager:
                    # 扫描目录更新状态
                    state_manager.scan_directory()
                    state_manager.update_sync_timestamp()
                    state_manager.save_cache()
            
            # 获取当前HEAD提交
            repo = Repo(repo_path)
            current_head = repo.head.commit.hexsha
            
            # 记录同步信息
            sync_info = {
                "path": str(repo_path),
                "last_commit": current_head,
                "last_sync": time.time()
            }
            
            return {
                "status": "success",
                "message": "Git仓库已存在",
                "is_new": False,
                "path": str(repo_path),
                "head_commit": current_head,
                "sync_info": sync_info
            }
        
        # 如果强制初始化且目录存在，清理目录
        if force and (repo_path / ".git").exists():
            shutil.rmtree(repo_path / ".git")
        
        # 初始化新仓库
        repo = Repo.init(repo_path)
        
        # 设置用户信息（如果不存在）
        config = repo.config_reader()
        try:
            username = config.get_value("user", "name")
            email = config.get_value("user", "email")
        except (KeyError, AttributeError):
            config_writer = repo.config_writer()
            config_writer.set_value("user", "name", "Sync-HTTP-MCP")
            config_writer.set_value("user", "email", "sync-mcp@example.com")
            username = "Sync-HTTP-MCP"
            email = "sync-mcp@example.com"
            config_writer.release()
        
        # 创建.gitignore文件
        gitignore_path = repo_path / ".gitignore"
        if not gitignore_path.exists() or force:
            gitignore_content = """# Sync-HTTP-MCP generated .gitignore
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
            with open(gitignore_path, "w") as f:
                f.write(gitignore_content)
        
        # 创建初始提交
        repo.git.add(all=True)
        repo.git.commit("-m", "Initial commit by Sync-HTTP-MCP")
        
        # 获取当前HEAD提交
        current_head = repo.head.commit.hexsha
        
        # 记录同步信息
        sync_info = {
            "path": str(repo_path),
            "last_commit": current_head,
            "last_sync": time.time()
        }
        
        # 创建并初始化状态管理器
        if GIT_STATE_AVAILABLE:
            state_manager = get_or_create_state_manager(str(repo_path))
            if state_manager:
                # 扫描目录生成初始状态
                state_manager.scan_directory()
                state_manager.update_sync_timestamp()
                state_manager.save_cache()
        
        return {
            "status": "success",
            "message": "Git仓库初始化成功",
            "is_new": True,
            "path": str(repo_path),
            "head_commit": current_head,
            "sync_info": sync_info
        }
    
    except Exception as e:
        logger.error(f"初始化Git仓库失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": f"初始化Git仓库失败: {str(e)}"
        }


def apply_git_patch(path: str, patch_content: str, binary_files: List[Dict[str, str]] = [], 
                    base_commit: Optional[str] = None) -> Dict[str, Any]:
    """
    应用Git补丁到仓库
    
    Args:
        path: 仓库路径
        patch_content: 补丁内容（base64编码）
        binary_files: 二进制文件列表
        base_commit: 基础提交
        
    Returns:
        操作结果信息
    """
    # 路径映射
    path = map_remote_path(path)
    repo_path = Path(path)
    
    # 检查Git是否可用
    if not GIT_AVAILABLE:
        return {
            "status": "error",
            "message": "Git功能不可用，请安装GitPython库"
        }
    
    # 检查路径是否存在且是Git仓库
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return {
            "status": "error",
            "message": f"目标路径不是有效的Git仓库: {repo_path}"
        }
    
    try:
        # 解码补丁内容
        try:
            patch_bytes = base64.b64decode(patch_content)
            patch_text = patch_bytes.decode('utf-8')
        except Exception as e:
            return {
                "status": "error",
                "message": f"补丁解码失败: {str(e)}"
            }
        
        # 处理二进制文件
        for binary_file in binary_files:
            file_path = binary_file.get("path")
            content = binary_file.get("content")
            
            if not file_path or not content:
                continue
            
            # 解码内容
            try:
                file_content = base64.b64decode(content)
            except Exception as e:
                logger.error(f"二进制文件解码失败: {file_path} - {str(e)}")
                continue
            
            # 确保目录存在
            full_path = repo_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入文件
            with open(full_path, "wb") as f:
                f.write(file_content)
        
        # 创建临时补丁文件
        with tempfile.NamedTemporaryFile(suffix='.patch', delete=False, mode='w') as patch_file:
            patch_file.write(patch_text)
            patch_path = patch_file.name
        
        try:
            # 应用补丁
            repo = Repo(repo_path)
            
            # 如果指定了base_commit，先检查
            if base_commit:
                try:
                    # 检查base_commit是否存在
                    repo.git.cat_file('-e', base_commit)
                    
                    # 检查是否有本地未提交变更
                    if repo.is_dirty():
                        # 获取当前工作目录和索引的变更状态
                        status = repo.git.status('--porcelain')
                        if status.strip():
                            logger.warning(f"仓库有未提交变更，尝试自动提交: {status}")
                            repo.git.add(all=True)
                            repo.git.commit('-m', 'Auto-commit before applying patch')
                except GitCommandError:
                    # base_commit不存在，返回错误
                    return {
                        "status": "error",
                        "message": f"基础提交不存在: {base_commit}"
                    }
            
            # 尝试应用补丁
            result = apply_patch(repo, patch_text)
            
            # 如果应用成功，提交更改，否则返回冲突信息
            if result["status"] == "success":
                # 添加所有变更
                repo.git.add(all=True)
                
                # 提交变更
                commit = repo.index.commit("Apply sync patch")
                
                # 获取受影响的文件
                affected_files = extract_files_from_patch(patch_text)
                
                # 更新GitStateManager
                if GIT_STATE_AVAILABLE:
                    state_manager = get_or_create_state_manager(str(repo_path))
                    if state_manager:
                        # 重新扫描整个仓库以更新状态
                        state_manager.scan_directory()
                        
                        # 额外更新补丁中明确提到的文件状态
                        for file_path in affected_files:
                            try:
                                full_path = os.path.join(str(repo_path), file_path)
                                state_manager.update_file_state(full_path)
                            except Exception as e:
                                logger.error(f"更新文件状态失败: {file_path} - {str(e)}")
                        
                        # 更新同步时间戳并保存缓存
                        state_manager.update_sync_timestamp()
                        state_manager.save_cache()
                
                # 返回结果
                return {
                    "status": "success",
                    "message": "补丁应用成功",
                    "commit": str(commit),
                    "affected_files": affected_files
                }
            else:
                # 补丁应用失败，返回冲突信息
                return result
        
        finally:
            # 删除临时补丁文件
            if os.path.exists(patch_path):
                os.unlink(patch_path)
    
    except Exception as e:
        logger.error(f"应用Git补丁失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": f"应用Git补丁失败: {str(e)}"
        }


def apply_patch(repo, patch_content: str) -> Dict[str, Any]:
    """
    应用Git补丁文件
    
    Args:
        repo: Repo对象
        patch_content: 补丁内容
        
    Returns:
        操作结果字典
    """
    # 创建临时补丁文件
    import tempfile
    
    patch_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.patch') as f:
            patch_file = f.name
            f.write(patch_content)
        
        try:
            # 尝试应用补丁
            repo.git.apply(patch_file, check=True)
            
            # 将改动添加到索引
            repo.git.add(".")
            
            return {"success": True}
            
        except GitCommandError as e:
            # 检查是否因为冲突而失败
            if "patch does not apply" in str(e):
                logger.warning("应用补丁时发生冲突")
                
                # 尝试获取冲突文件
                conflict_files_list = []
                
                # 尝试分析补丁内容找出文件名
                affected_files = extract_files_from_patch(patch_content)
                
                # 对可能受影响的文件进行检查
                for file_path in affected_files:
                    full_path = Path(repo.working_dir) / file_path
                    if full_path.exists():
                        # 读取当前内容
                        with open(full_path, 'rb') as f:
                            current_content = f.read()
                        
                        conflict_files_list.append(GitConflictFile(
                            path=file_path,
                            remote_content=base64.b64encode(current_content).decode('utf-8')
                        ))
                
                return {
                    "success": False,
                    "message": "应用补丁时发生冲突",
                    "conflict_files": conflict_files_list
                }
            else:
                return {"success": False, "message": str(e)}
    
    finally:
        # 清理临时文件
        if patch_file and os.path.exists(patch_file):
            os.unlink(patch_file)


def extract_files_from_patch(patch_content: str) -> List[str]:
    """
    从Git补丁中提取文件路径
    
    Args:
        patch_content: 补丁内容
        
    Returns:
        文件路径列表
    """
    files = []
    
    try:
        # 解析补丁内容
        lines = patch_content.splitlines()
        current_file = None
        
        for line in lines:
            # 尝试识别文件头
            if line.startswith('--- a/') or line.startswith('+++ b/'):
                # 提取路径部分
                file_path = line[6:].strip()
                
                # 忽略/dev/null（表示文件创建或删除）
                if file_path != '/dev/null' and file_path not in files:
                    files.append(file_path)
            
            # 识别二进制文件
            elif line.startswith('Binary files '):
                # 格式通常是 "Binary files a/path/to/file and b/path/to/file differ"
                parts = line.split(' ')
                if len(parts) > 2:
                    a_file = parts[2]
                    if a_file.startswith('a/'):
                        file_path = a_file[2:]
                        if file_path not in files:
                            files.append(file_path)
            
            # 识别diff --git行，作为备选
            elif line.startswith('diff --git '):
                # 格式通常是 "diff --git a/path/to/file b/path/to/file"
                parts = line.split(' ')
                if len(parts) >= 4:
                    a_file = parts[2]
                    if a_file.startswith('a/'):
                        file_path = a_file[2:]
                        if file_path not in files:
                            files.append(file_path)
    
    except Exception as e:
        logger.error(f"从补丁提取文件失败: {str(e)}")
    
    return files


def resolve_conflicts(path: str, resolutions: List[GitConflictResolution]) -> Dict[str, Any]:
    """
    解决冲突
    
    Args:
        path: 仓库路径
        resolutions: 冲突解决列表
        
    Returns:
        操作结果字典
    """
    # 路径映射
    path = map_remote_path(path)
    
    repo_path = Path(path)
    
    if not (repo_path / ".git").exists():
        return {"status": "error", "message": "目标路径不是Git仓库"}
    
    try:
        repo = Repo(repo_path)
        
        # 检查是否有记录的冲突
        if str(repo_path) not in conflict_files or not conflict_files[str(repo_path)]:
            return {"status": "error", "message": "没有需要解决的冲突"}
        
        # 按照解决方案处理冲突
        for resolution in resolutions:
            resolved = False
            
            # 查找对应的冲突文件
            for i, cf in enumerate(conflict_files[str(repo_path)]):
                if cf.path == resolution.path:
                    file_path = repo_path / cf.path
                    
                    if resolution.resolution == "local":
                        # 使用本地版本，不做任何事
                        resolved = True
                    elif resolution.resolution == "remote":
                        # 使用远程版本
                        if cf.remote_content:
                            with open(file_path, 'wb') as f:
                                f.write(base64.b64decode(cf.remote_content))
                            resolved = True
                    elif resolution.resolution == "merged":
                        # 使用合并版本
                        if resolution.content:
                            with open(file_path, 'wb') as f:
                                f.write(base64.b64decode(resolution.content))
                            resolved = True
                    
                    if resolved:
                        # 从冲突列表中删除
                        conflict_files[str(repo_path)].pop(i)
                        break
        
        # 添加解决后的文件
        for resolution in resolutions:
            file_path = repo_path / resolution.path
            if file_path.exists():
                repo.git.add(str(file_path))
        
        # 如果没有冲突了，提交变更
        if not conflict_files[str(repo_path)]:
            commit = repo.index.commit("解决同步冲突")
            
            # 更新同步信息
            if str(repo_path) in git_sync_info:
                git_sync_info[str(repo_path)]["last_sync"] = time.time()
                git_sync_info[str(repo_path)]["last_commit"] = str(commit)
            
            return {
                "status": "success",
                "message": "冲突已解决",
                "new_commit": str(commit)
            }
        else:
            # 还有未解决的冲突
            return {
                "status": "partial",
                "message": "部分冲突已解决",
                "remaining_conflicts": len(conflict_files[str(repo_path)])
            }
        
    except Exception as e:
        logger.error(f"解决冲突失败: {str(e)}")
        return {"status": "error", "message": f"解决冲突失败: {str(e)}"}


def get_sync_status(path: str) -> Dict[str, Any]:
    """
    获取同步状态
    
    Args:
        path: 仓库路径
        
    Returns:
        状态信息字典
    """
    # 路径映射
    path = map_remote_path(path)
    
    repo_path = Path(path)
    
    if not (repo_path / ".git").exists():
        return {"status": "error", "message": "目标路径不是Git仓库"}
    
    try:
        repo = Repo(repo_path)
        
        # 检查是否有未提交的变更
        is_dirty = repo.is_dirty()
        
        # 获取最后一次提交
        last_commit = None
        commit_time = None
        commit_message = None
        
        if len(repo.heads) > 0:
            last_commit = str(repo.head.commit)
            commit_time = repo.head.commit.committed_datetime.isoformat()
            commit_message = repo.head.commit.message
        
        # 获取分支信息
        current_branch = None
        if repo.head.is_detached:
            current_branch = "detached"
        else:
            current_branch = repo.active_branch.name
        
        # 获取工作区文件状态
        status = {}
        for item in repo.index.diff(None):
            status[str(item.a_path)] = item.change_type
        
        # 获取已添加但未提交的文件
        for item in repo.index.diff("HEAD"):
            status[str(item.a_path)] = item.change_type
        
        # 获取未跟踪的文件
        for item in repo.untracked_files:
            status[str(item)] = "untracked"
        
        return {
            "status": "success",
            "is_dirty": is_dirty,
            "last_commit": last_commit,
            "commit_time": commit_time,
            "commit_message": commit_message,
            "current_branch": current_branch,
            "file_status": status,
            "conflict_files": len(conflict_files.get(str(repo_path), [])) if str(repo_path) in conflict_files else 0
        }
        
    except Exception as e:
        logger.error(f"获取同步状态失败: {str(e)}")
        return {"status": "error", "message": f"获取同步状态失败: {str(e)}"}


def get_conflicts(path: str) -> Dict[str, Any]:
    """
    获取冲突信息
    
    Args:
        path: 仓库路径
        
    Returns:
        冲突信息字典
    """
    # 路径映射
    path = map_remote_path(path)
    
    repo_path = Path(path)
    
    if not (repo_path / ".git").exists():
        return {"status": "error", "message": "目标路径不是Git仓库"}
    
    try:
        # 检查是否有记录的冲突
        if str(repo_path) not in conflict_files or not conflict_files[str(repo_path)]:
            return {
                "status": "success",
                "conflicts": []
            }
        
        # 获取冲突文件列表
        conflicts = []
        for cf in conflict_files[str(repo_path)]:
            file_path = repo_path / cf.path
            
            # 如果文件不存在，跳过
            if not file_path.exists():
                continue
            
            conflicts.append({
                "path": cf.path,
                "content": cf.content
            })
        
        return {
            "status": "success",
            "conflicts": conflicts
        }
        
    except Exception as e:
        logger.error(f"获取冲突信息失败: {str(e)}")
        return {"status": "error", "message": f"获取冲突信息失败: {str(e)}"}

CACHE_FILE = Path(__file__).parent / ".remote_cache.json" # Cache file path


# WebSocket连接管理
class ConnectionManager:
    """管理WebSocket连接"""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """处理新的WebSocket连接"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket连接已建立")

    def disconnect(self, websocket: WebSocket):
        """处理WebSocket断开连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket连接已断开")

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        for connection in self.active_connections:
            await connection.send_json(message)
        logger.debug(f"消息已广播: {message}")


manager = ConnectionManager()


# 辅助函数
def get_file_info(path: str) -> FileInfo:
    """获取文件信息"""
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件或目录不存在: {path}")
    
    if file_path.is_dir():
        return FileInfo(
            name=file_path.name,
            path=str(file_path),
            type="directory"
        )
    else:
        stats = file_path.stat()
        return FileInfo(
            name=file_path.name,
            path=str(file_path),
            type="file",
            size=stats.st_size,
            last_modified=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stats.st_mtime))
        )


async def read_file_content(path: str) -> dict:
    """读取文件内容"""
    # 路径映射
    path = map_remote_path(path)
    
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    
    if file_path.is_dir():
        raise HTTPException(status_code=400, detail=f"路径指向目录而非文件: {path}")
    
    try:
        stats = file_path.stat()
        async with aiofiles.open(file_path, 'rb') as f:
            content = await f.read()
        
        # 计算MD5校验和
        checksum = hashlib.md5(content).hexdigest()
        
        # Base64编码内容
        encoded_content = base64.b64encode(content).decode('utf-8')
        
        # 生成文件元数据
        metadata = await generate_file_metadata(str(file_path), content)
        
        return {
            "content": encoded_content,
            "path": str(file_path),
            "last_modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stats.st_mtime)),
            "checksum": checksum,
            "metadata": metadata
        }
    except Exception as e:
        logger.error(f"读取文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")


async def write_file_content(file_content: FileContent) -> dict:
    """写入文件内容"""
    # 路径映射
    file_content.path = map_remote_path(file_content.path)
    file_path = Path(file_content.path)
    
    # 确保父目录存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # 解码Base64内容
        content = base64.b64decode(file_content.content)
        
        # 如果提供了校验和，进行验证
        if file_content.checksum:
            calculated_checksum = hashlib.md5(content).hexdigest()
            if calculated_checksum != file_content.checksum:
                raise HTTPException(
                    status_code=400, 
                    detail=f"校验和不匹配: 期望 {file_content.checksum}, 实际 {calculated_checksum}"
                )
        
        # 写入文件
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)
        
        # 获取更新后的文件信息
        stats = file_path.stat()
        
        # 更新文件元数据
        metadata = await generate_file_metadata(str(file_path), content)
        
        return {
            "status": "success",
            "path": str(file_path),
            "last_modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stats.st_mtime)),
            "metadata": metadata
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"写入文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"写入文件失败: {str(e)}")


async def execute_command(command_request: CommandRequest) -> str:
    """在后台执行命令"""
    command_id = str(uuid.uuid4())
    command = command_request.command
    working_dir = command_request.working_directory
    env = command_request.environment or {}
    timeout = command_request.timeout or 300
    
    # 记录命令信息
    active_commands[command_id] = {
        "command": command,
        "working_directory": working_dir,
        "status": "pending",
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())),
        "end_time": None,
        "exit_code": None,
        "output": "",
        "process": None
    }
    
    # 异步执行命令
    asyncio.create_task(run_command(command_id, command, working_dir, env, timeout))
    
    return command_id


async def run_command(command_id: str, command: str, working_dir: str, env: dict, timeout: int):
    """运行命令并捕获输出"""
    try:
        # 更新命令状态
        active_commands[command_id]["status"] = "running"
        
        # 设置环境变量
        cmd_env = os.environ.copy()
        for key, value in env.items():
            cmd_env[key] = str(value)
        
        # 创建目录（如果不存在）
        os.makedirs(working_dir, exist_ok=True)
        
        # 启动进程
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=cmd_env
        )
        
        active_commands[command_id]["process"] = process
        
        # 读取标准输出和标准错误
        stdout_task = asyncio.create_task(read_stream(process.stdout, command_id, "stdout"))
        stderr_task = asyncio.create_task(read_stream(process.stderr, command_id, "stderr"))
        
        # 等待命令执行完成或超时
        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=timeout)
            active_commands[command_id]["exit_code"] = exit_code
            active_commands[command_id]["status"] = "completed"
        except asyncio.TimeoutError:
            # 命令执行超时
            active_commands[command_id]["status"] = "timeout"
            process.terminate()
            await asyncio.sleep(1)
            if process.returncode is None:
                process.kill()
        
        # 等待输出读取完成
        await asyncio.gather(stdout_task, stderr_task)
        
        # 更新结束时间
        active_commands[command_id]["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))
        
        # 广播命令完成通知
        await manager.broadcast({
            "type": "command_completed",
            "command_id": command_id,
            "status": active_commands[command_id]["status"],
            "exit_code": active_commands[command_id]["exit_code"]
        })
        
    except Exception as e:
        # 处理命令执行过程中的异常
        logger.error(f"命令执行错误: {str(e)}")
        active_commands[command_id]["status"] = "failed"
        active_commands[command_id]["output"] += f"\n执行错误: {str(e)}"
        active_commands[command_id]["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))


async def read_stream(stream, command_id: str, stream_name: str):
    """读取流内容并更新命令输出"""
    output_buffer = []
    
    while True:
        line = await stream.readline()
        if not line:
            break
        
        line_text = line.decode('utf-8', errors='replace')
        output_buffer.append(line_text)
        active_commands[command_id]["output"] += line_text
        
        # 广播输出更新通知
        await manager.broadcast({
            "type": "command_output",
            "command_id": command_id,
            "stream": stream_name,
            "content": line_text
        })


# 增量同步相关函数
async def generate_file_metadata(file_path: str, content: Optional[bytes] = None) -> Dict:
    """
    生成文件的元数据，包括块哈希值
    
    Args:
        file_path: 文件路径
        content: 可选的文件内容，如果提供则使用内存中内容而非重新读取文件
        
    Returns:
        文件元数据字典
    """
    path_obj = Path(file_path)
    if not content:
        if not path_obj.exists() or not path_obj.is_file():
            raise HTTPException(status_code=404, detail=f"文件不存在或不是常规文件: {file_path}")
        
        # 读取文件内容
        async with aiofiles.open(path_obj, 'rb') as f:
            content = await f.read()
    
    # 获取文件信息
    if path_obj.exists():
        stat = path_obj.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    else:
        # 如果是新创建的文件，文件尚未被写入
        mtime = time.time()
        size = len(content)
    
    # 计算块哈希值（使用4KB块大小）
    block_size = 4096
    blocks = {}
    full_hasher = hashlib.md5()
    
    # 分块处理内容
    for i in range(0, len(content), block_size):
        block_data = content[i:i+block_size]
        block_index = i // block_size
        
        # 更新完整哈希
        full_hasher.update(block_data)
        
        # 计算块哈希
        block_hasher = hashlib.md5()
        block_hasher.update(block_data)
        blocks[str(block_index)] = block_hasher.hexdigest()
    
    full_hash = full_hasher.hexdigest()
    
    # 构建元数据
    metadata = {
        "path": str(path_obj),
        "mtime": mtime,
        "size": size,
        "full_hash": full_hash,
        "blocks": blocks
    }
    
    # 缓存元数据
    file_metadata_cache[str(path_obj)] = metadata
    
    return metadata


async def process_delta_content(delta_content: DeltaContent) -> Dict:
    """
    处理增量同步内容
    
    Args:
        delta_content: 增量内容对象
        
    Returns:
        处理结果字典
    """
    # 路径映射
    delta_content.path = map_remote_path(delta_content.path)
    file_path = Path(delta_content.path)
    
    # 确保父目录存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        if delta_content.delta_type == "none":
            # 文件未变更，无需操作
            logger.info(f"文件未变更: {file_path}")
            
            # 如果存在缓存的元数据，返回
            if str(file_path) in file_metadata_cache:
                metadata = file_metadata_cache[str(file_path)]
            else:
                # 如果文件存在，生成元数据
                if file_path.exists():
                    metadata = await generate_file_metadata(str(file_path))
                else:
                    return {
                        "status": "error",
                        "path": str(file_path),
                        "message": "文件不存在且未提供内容"
                    }
            
            return {
                "status": "success",
                "path": str(file_path),
                "message": "文件未变更",
                "metadata": metadata
            }
        
        elif delta_content.delta_type == "full":
            # 完整文件传输
            if delta_content.content:
                # 解码Base64内容
                content = base64.b64decode(delta_content.content)
                
                # 写入文件
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(content)
                
                # 生成元数据
                metadata = await generate_file_metadata(str(file_path), content)
                
                logger.info(f"文件完整更新: {file_path}")
                return {
                    "status": "success",
                    "path": str(file_path),
                    "message": "文件已完整更新",
                    "metadata": metadata
                }
            else:
                return {
                    "status": "error",
                    "path": str(file_path),
                    "message": "完整传输模式但未提供内容"
                }
        
        elif delta_content.delta_type == "delta":
            # 增量更新 - 仅更新变更的块
            if not delta_content.blocks:
                return {
                    "status": "error",
                    "path": str(file_path),
                    "message": "增量传输模式但未提供块数据"
                }
            
            # 如果文件不存在，无法应用增量更新
            if not file_path.exists():
                return {
                    "status": "error",
                    "path": str(file_path),
                    "message": "文件不存在，无法应用增量更新"
                }
            
            # 读取现有文件
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
            
            # 将内容转换为可变字节数组
            content_array = bytearray(content)
            block_size = 4096
            
            # 应用增量更新
            for block_index_str, block_data_b64 in delta_content.blocks.items():
                block_index = int(block_index_str)
                block_data = base64.b64decode(block_data_b64)
                
                start_pos = block_index * block_size
                end_pos = start_pos + len(block_data)
                
                # 确保数组大小足够
                if end_pos > len(content_array):
                    content_array.extend(b'\0' * (end_pos - len(content_array)))
                
                # 更新块
                content_array[start_pos:end_pos] = block_data
            
            # 写入更新后的文件
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content_array)
            
            # 生成元数据
            metadata = await generate_file_metadata(str(file_path), bytes(content_array))
            
            logger.info(f"文件增量更新: {file_path}")
            return {
                "status": "success",
                "path": str(file_path),
                "message": "文件已增量更新",
                "metadata": metadata
            }
        
        else:
            return {
                "status": "error",
                "path": str(file_path),
                "message": f"不支持的同步类型: {delta_content.delta_type}"
            }
    
    except Exception as e:
        logger.error(f"处理增量内容失败: {str(e)}")
        return {
            "status": "error",
            "path": str(file_path),
            "message": f"处理失败: {str(e)}"
        }


# API端点
@app.get("/")
def read_root():
    """根路由，返回服务器信息"""
    return {
        "name": "Sync-HTTP-MCP Remote Server",
        "version": "0.2.0",
        "delta_sync_supported": True,
        "git_sync_supported": GIT_AVAILABLE
    }


@app.get("/api/v1/files")
def list_files(path: str):
    """列出目录内容"""
    # 路径映射
    path = map_remote_path(path)
    
    dir_path = Path(path)
    if not dir_path.exists():
        raise HTTPException(status_code=404, detail=f"目录不存在: {path}")
    
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"路径不是目录: {path}")
    
    files = []
    for item in dir_path.iterdir():
        files.append(get_file_info(str(item)))
    
    return {"files": files}


@app.get("/api/v1/files/content")
async def get_file_content(path: str):
    """获取文件内容"""
    return await read_file_content(path)


@app.put("/api/v1/files/content")
async def update_file_content(file_content: FileContent):
    """更新文件内容"""
    result = await write_file_content(file_content)
    
    # 广播文件变更事件
    await manager.broadcast({
        "type": "file_changed",
        "path": file_content.path,
        "action": "updated"
    })
    
    return result


@app.put("/api/v1/files/delta")
async def update_file_delta(delta_content: DeltaContent):
    """更新文件内容（增量）"""
    result = await process_delta_content(delta_content)
    
    # 广播文件变更事件
    await manager.broadcast({
        "type": "file_changed",
        "path": delta_content.path,
        "action": "updated"
    })
    
    return result


@app.post("/api/v1/files/sync")
async def sync_files(file_sync: FileSyncRequest):
    """批量同步文件"""
    results = []
    synchronized = 0
    failed = 0
    
    for file_content in file_sync.files:
        try:
            result = await write_file_content(file_content)
            results.append({
                "path": file_content.path,
                "status": "success"
            })
            synchronized += 1
            
            # 广播文件变更事件
            await manager.broadcast({
                "type": "file_changed",
                "path": file_content.path,
                "action": "updated"
            })
            
        except Exception as e:
            results.append({
                "path": file_content.path,
                "status": "error",
                "message": str(e)
            })
            failed += 1
    
    return {
        "status": "success",
        "synchronized": synchronized,
        "failed": failed,
        "details": results
    }


@app.post("/api/v1/files/delta_sync")
async def delta_sync_files(delta_sync: DeltaSyncRequest):
    """批量增量同步文件"""
    results = []
    synchronized = 0
    failed = 0
    metadata_dict = {}
    
    for delta_content in delta_sync.files:
        try:
            result = await process_delta_content(delta_content)
            if result["status"] == "success":
                results.append({
                    "path": delta_content.path,
                    "status": "success"
                })
                synchronized += 1
                
                # 保存元数据以返回
                if "metadata" in result:
                    metadata_dict[delta_content.path] = result["metadata"]
                
                # 广播文件变更事件
                await manager.broadcast({
                    "type": "file_changed",
                    "path": delta_content.path,
                    "action": "updated",
                    "delta_type": delta_content.delta_type
                })
            else:
                results.append({
                    "path": delta_content.path,
                    "status": "error",
                    "message": result.get("message", "未知错误")
                })
                failed += 1
            
        except Exception as e:
            results.append({
                "path": delta_content.path,
                "status": "error",
                "message": str(e)
            })
            failed += 1
    
    return {
        "status": "success",
        "synchronized": synchronized,
        "failed": failed,
        "details": results,
        "metadata": metadata_dict
    }


@app.post("/api/v1/commands")
async def execute_command_api(command_request: CommandRequest):
    """执行命令API"""
    command_id = await execute_command(command_request)
    return {
        "command_id": command_id,
        "status": active_commands[command_id]["status"],
        "start_time": active_commands[command_id]["start_time"]
    }


@app.get("/api/v1/commands/{command_id}")
def get_command_status(command_id: str):
    """获取命令状态"""
    if command_id not in active_commands:
        raise HTTPException(status_code=404, detail=f"未找到命令: {command_id}")
    
    command_info = active_commands[command_id]
    return {
        "command_id": command_id,
        "status": command_info["status"],
        "start_time": command_info["start_time"],
        "end_time": command_info["end_time"],
        "exit_code": command_info["exit_code"],
        "output_url": f"/api/v1/commands/{command_id}/output"
    }


@app.get("/api/v1/commands/{command_id}/output")
def get_command_output(command_id: str):
    """获取命令输出"""
    if command_id not in active_commands:
        raise HTTPException(status_code=404, detail=f"未找到命令: {command_id}")
    
    command_info = active_commands[command_id]
    return {
        "output": command_info["output"],
        "is_complete": command_info["status"] in ["completed", "failed", "timeout"]
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket连接处理"""
    await manager.connect(websocket)
    try:
        while True:
            # 等待客户端消息
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理消息
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.on_event("startup")
async def startup_event():
    """服务器启动事件处理"""
    # 初始化Git状态管理器
    if SERVER_CONFIG["git_cache_enabled"] and GIT_STATE_AVAILABLE:
        await load_git_state_cache()
    
    # 创建测试模式目录结构
    if SERVER_CONFIG["test_mode"]:
        os.makedirs(SERVER_CONFIG["test_root_dir"], exist_ok=True)
        # 创建基本目录结构，例如 /home
        os.makedirs(os.path.join(SERVER_CONFIG["test_root_dir"], "home"), exist_ok=True)
        logger.info(f"已创建测试模式目录结构: {SERVER_CONFIG['test_root_dir']}")


@app.on_event("shutdown")
async def shutdown_event():
    """服务器关闭事件处理"""
    # 保存Git状态缓存
    if SERVER_CONFIG["git_cache_enabled"] and GIT_STATE_AVAILABLE:
        await save_git_state_cache()


async def load_git_state_cache():
    """加载Git状态缓存"""
    if not GIT_STATE_AVAILABLE:
        logger.warning("Git状态管理模块不可用，无法加载缓存")
        return
    
    # 确保缓存目录存在
    cache_dir = os.path.expanduser(SERVER_CONFIG["cache_dir"])
    os.makedirs(cache_dir, exist_ok=True)
    
    # 尝试从缓存目录加载现有的状态管理器
    try:
        cache_files = [f for f in os.listdir(cache_dir) if f.endswith('.json')]
        for cache_file in cache_files:
            # 从文件名提取路径信息
            path_hash = cache_file.replace('.json', '')
            
            # 尝试从缓存文件加载
            cache_path = os.path.join(cache_dir, cache_file)
            
            # 创建状态管理器并加载缓存
            try:
                # 从缓存JSON文件中提取原始路径
                with open(cache_path, 'r') as f:
                    cache_data = json.load(f)
                    original_path = cache_data.get('base_dir', '')
                
                if original_path:
                    # 创建状态管理器
                    manager = GitStateManager(original_path, cache_path)
                    if manager.load_cache():
                        GIT_STATE_MANAGERS[original_path] = manager
                        logger.info(f"已加载Git状态缓存: {original_path}")
            except Exception as e:
                logger.error(f"加载Git状态缓存失败: {cache_path} - {str(e)}")
    except Exception as e:
        logger.error(f"加载Git状态缓存目录失败: {cache_dir} - {str(e)}")


async def save_git_state_cache():
    """保存Git状态缓存"""
    if not GIT_STATE_AVAILABLE:
        return
    
    # 保存所有状态管理器的缓存
    for path, manager in GIT_STATE_MANAGERS.items():
        try:
            if manager.save_cache():
                logger.info(f"已保存Git状态缓存: {path}")
            else:
                logger.warning(f"保存Git状态缓存失败: {path}")
        except Exception as e:
            logger.error(f"保存Git状态缓存异常: {path} - {str(e)}")


def get_or_create_state_manager(path: str) -> Optional[GitStateManager]:
    """获取或创建Git状态管理器"""
    if not GIT_STATE_AVAILABLE:
        return None
    
    # 规范化路径
    path = os.path.normpath(path)
    
    # 检查是否已存在
    if path in GIT_STATE_MANAGERS:
        return GIT_STATE_MANAGERS[path]
    
    # 创建新的状态管理器
    if SERVER_CONFIG["git_cache_enabled"]:
        # 为此路径创建缓存文件
        cache_dir = os.path.expanduser(SERVER_CONFIG["cache_dir"])
        os.makedirs(cache_dir, exist_ok=True)
        
        # 使用路径哈希作为缓存文件名
        path_hash = hashlib.md5(path.encode()).hexdigest()
        cache_path = os.path.join(cache_dir, f"{path_hash}.json")
        
        # 创建状态管理器
        manager = GitStateManager(path, cache_path)
        GIT_STATE_MANAGERS[path] = manager
        return manager
    else:
        # 不启用缓存
        manager = GitStateManager(path)
        GIT_STATE_MANAGERS[path] = manager
        return manager


# 如果作为主程序运行
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync-HTTP-MCP远程服务器")
    parser.add_argument("--host", default="127.0.0.1", help="服务器主机地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8081, help="服务器端口 (默认: 8081)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                      help="日志级别 (默认: INFO)")
    parser.add_argument("--test-mode", action="store_true", help="启用测试模式，使用本地虚拟路径")
    parser.add_argument("--test-root", help="测试模式根目录 (默认: ~/mcp_test_root)")
    parser.add_argument("--cache-dir", help="Git状态缓存目录 (默认: ~/.mcp_cache)")
    parser.add_argument("--disable-git-cache", action="store_true", help="禁用Git状态缓存")
    
    args = parser.parse_args()
    
    # 配置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # 更新程序配置
    if args.test_mode:
        SERVER_CONFIG["test_mode"] = True
        if args.test_root:
            SERVER_CONFIG["test_root_dir"] = args.test_root
        logger.info(f"已启用测试模式")
        logger.info(f"测试模式根目录: {SERVER_CONFIG['test_root_dir']}")
    
    # 设置Git缓存配置
    if args.cache_dir:
        SERVER_CONFIG["cache_dir"] = args.cache_dir
    
    if args.disable_git_cache:
        SERVER_CONFIG["git_cache_enabled"] = False
        logger.info("已禁用Git状态缓存")
    
    # 启动服务器
    uvicorn.run(app, host=args.host, port=args.port)