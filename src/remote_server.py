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
    "test_root_dir": str(Path.home() / "mcp_test_root")  # 测试模式下的虚拟根目录，默认为用户主目录下的mcp_test_root
}

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
        操作结果字典
    """
    if not GIT_AVAILABLE:
        return {"status": "error", "message": "Git功能不可用，请安装GitPython库"}
    
    # 路径映射
    path = map_remote_path(path)
    
    repo_path = Path(path)
    
    # 确保目录存在
    try:
        repo_path.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        return {"status": "error", "message": f"权限错误: 无法创建目录 {repo_path}"}
    except FileNotFoundError as e:
        return {"status": "error", "message": f"路径错误: 无法创建目录 {repo_path}"}
    
    git_dir = repo_path / ".git"
    
    try:
        if git_dir.exists() and not force:
            # 检查是否为有效的Git仓库
            try:
                repo = Repo(repo_path)
                if not repo.bare:
                    # 仓库已存在且有效
                    last_commit = None
                    if len(repo.heads) > 0:
                        last_commit = str(repo.head.commit)
                    
                    git_sync_info[str(repo_path)] = {
                        "repo": repo,
                        "last_sync": time.time(),
                        "last_commit": last_commit
                    }
                    
                    return {
                        "status": "success", 
                        "message": "仓库已存在", 
                        "path": str(repo_path),
                        "last_commit": last_commit
                    }
                else:
                    return {"status": "error", "message": "目标路径是一个裸仓库"}
            except GitCommandError:
                if force:
                    # 无效的仓库，但允许强制重新初始化
                    logger.warning(f"强制删除无效的Git仓库: {repo_path}")
                    shutil.rmtree(git_dir)
                else:
                    return {"status": "error", "message": "目标路径中存在无效的Git仓库"}
        
        # 初始化新仓库
        repo = Repo.init(repo_path)
        
        # 创建初始提交以建立主分支
        # 创建.gitignore文件
        gitignore_path = repo_path / ".gitignore"
        gitignore_content = """
# 默认忽略规则
.DS_Store
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.env
.venv
env/
venv/
ENV/
*.log
"""
        with open(gitignore_path, 'w') as f:
            f.write(gitignore_content)
        
        # 创建README.md文件
        readme_path = repo_path / "README.md"
        with open(readme_path, 'w') as f:
            f.write(f"# 同步目录: {repo_path.name}\n\n这个目录由Sync-HTTP-MCP管理，用于远程代码同步。")
        
        # 添加并提交文件
        repo.git.add(".gitignore", "README.md")
        commit = repo.index.commit("初始化同步仓库")
        
        # 保存仓库信息
        git_sync_info[str(repo_path)] = {
            "repo": repo,
            "last_sync": time.time(),
            "last_commit": str(commit)
        }
        
        return {
            "status": "success", 
            "message": "仓库已初始化", 
            "path": str(repo_path),
            "last_commit": str(commit)
        }
        
    except Exception as e:
        logger.error(f"初始化Git仓库失败: {str(e)}")
        return {"status": "error", "message": f"初始化Git仓库失败: {str(e)}"}


def apply_git_patch(path: str, patch_content: str, binary_files: List[Dict[str, str]] = [], 
                    base_commit: Optional[str] = None) -> Dict[str, Any]:
    """
    应用Git补丁
    
    Args:
        path: 仓库路径
        patch_content: 补丁内容
        binary_files: 二进制文件列表
        base_commit: 基准提交哈希
        
    Returns:
        操作结果字典
    """
    if not GIT_AVAILABLE:
        return {"status": "error", "message": "Git功能不可用，请安装GitPython库"}
    
    # 路径映射
    path = map_remote_path(path)
    
    repo_path = Path(path)
    
    if not (repo_path / ".git").exists():
        return {"status": "error", "message": "目标路径不是Git仓库"}
    
    try:
        repo = Repo(repo_path)
        
        # 验证base_commit是否存在
        if base_commit:
            try:
                repo.git.rev_parse(base_commit)
            except GitCommandError:
                return {"status": "error", "message": f"基准提交不存在: {base_commit}"}
        
        # 首先应用二进制文件
        for binary_file in binary_files:
            file_path = repo_path / binary_file["path"].lstrip('/')
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            content = base64.b64decode(binary_file["content"])
            with open(file_path, 'wb') as f:
                f.write(content)
            
            # 添加到索引
            repo.git.add(str(file_path))
        
        # 应用补丁
        patch_result = apply_patch(repo, patch_content)
        
        if not patch_result["success"]:
            if patch_result.get("conflict_files"):
                # 记录冲突文件
                conflict_files[str(repo_path)] = patch_result["conflict_files"]
                
                # 返回冲突信息
                return {
                    "status": "conflict",
                    "message": "应用补丁时发生冲突",
                    "conflicts": [{"path": cf.path} for cf in patch_result["conflict_files"]]
                }
            else:
                return {"status": "error", "message": patch_result.get("message", "应用补丁失败")}
        
        # 创建提交
        commit_message = "从客户端同步变更"
        commit = repo.index.commit(commit_message)
        
        # 更新同步信息
        if str(repo_path) in git_sync_info:
            git_sync_info[str(repo_path)]["last_sync"] = time.time()
            git_sync_info[str(repo_path)]["last_commit"] = str(commit)
        else:
            git_sync_info[str(repo_path)] = {
                "repo": repo,
                "last_sync": time.time(),
                "last_commit": str(commit)
            }
        
        return {
            "status": "success",
            "message": "补丁已应用",
            "new_commit": str(commit)
        }
        
    except Exception as e:
        logger.error(f"应用Git补丁失败: {str(e)}")
        return {"status": "error", "message": f"应用Git补丁失败: {str(e)}"}


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
    从补丁内容中提取文件名
    
    Args:
        patch_content: 补丁内容
        
    Returns:
        文件路径列表
    """
    files = []
    lines = patch_content.splitlines()
    
    for line in lines:
        if line.startswith("diff --git "):
            # 格式：diff --git a/path/to/file b/path/to/file
            parts = line.split(" ")
            if len(parts) >= 4:
                b_path = parts[3][2:]  # 移除 "b/" 前缀
                files.append(b_path)
    
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


<<<<<<< HEAD
# Git同步API端点
@app.post("/api/v1/sync/init")
def init_sync_repo(git_init: GitInitRequest):
    """初始化同步仓库"""
    if not GIT_AVAILABLE:
        raise HTTPException(status_code=400, detail="Git功能不可用，请安装GitPython库")
    
    result = init_git_repo(git_init.path, git_init.force)
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@app.post("/api/v1/sync/patch")
def apply_sync_patch(patch_request: GitPatchRequest):
    """应用同步补丁"""
    if not GIT_AVAILABLE:
        raise HTTPException(status_code=400, detail="Git功能不可用，请安装GitPython库")
    
    # 识别仓库路径（通过Git信息缓存）
    if not git_sync_info:
        raise HTTPException(status_code=400, detail="没有已初始化的Git仓库")
    
    # 找到匹配base_commit的仓库
    repo_path = None
    for path, info in git_sync_info.items():
        if info.get("last_commit") == patch_request.base_commit:
            repo_path = path
            break
    
    if not repo_path:
        # 如果没有找到匹配的仓库，使用第一个仓库
        repo_path = next(iter(git_sync_info.keys()))
    
    result = apply_git_patch(
        repo_path, 
        patch_request.patch_content, 
        patch_request.binary_files, 
        patch_request.base_commit
    )
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@app.get("/api/v1/sync/status")
def get_sync_repo_status(path: Optional[str] = None):
    """获取同步状态"""
    if not GIT_AVAILABLE:
        raise HTTPException(status_code=400, detail="Git功能不可用，请安装GitPython库")
    
    # 如果未指定路径，使用第一个仓库
    if not path:
        if not git_sync_info:
            return {"status": "not_initialized", "message": "没有已初始化的Git仓库"}
        path = next(iter(git_sync_info.keys()))
    
    # 路径映射
    path = map_remote_path(path)
    
    result = get_sync_status(path)
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@app.get("/api/v1/sync/conflicts")
def get_sync_conflicts(path: Optional[str] = None):
    """获取冲突信息"""
    if not GIT_AVAILABLE:
        raise HTTPException(status_code=400, detail="Git功能不可用，请安装GitPython库")
    
    # 如果未指定路径，使用第一个仓库
    if not path:
        if not git_sync_info:
            return {"status": "not_initialized", "message": "没有已初始化的Git仓库"}
        
        # 查找有冲突的仓库
        conflict_repo = None
        for repo_path in git_sync_info:
            if repo_path in conflict_files and conflict_files[repo_path]:
                conflict_repo = repo_path
                break
        
        if not conflict_repo:
            # 如果没有找到有冲突的仓库，使用第一个仓库
            path = next(iter(git_sync_info.keys()))
        else:
            path = conflict_repo
    
    # 路径映射
    path = map_remote_path(path)
    
    result = get_conflicts(path)
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@app.post("/api/v1/sync/resolve")
def resolve_sync_conflicts(resolve_request: GitConflictResolutionRequest, path: Optional[str] = None):
    """解决同步冲突"""
    if not GIT_AVAILABLE:
        raise HTTPException(status_code=400, detail="Git功能不可用，请安装GitPython库")
    
    # 如果未指定路径，使用第一个仓库
    if not path:
        if not git_sync_info:
            raise HTTPException(status_code=400, detail="没有已初始化的Git仓库")
        
        # 查找有冲突的仓库
        conflict_repo = None
        for repo_path in git_sync_info:
            if repo_path in conflict_files and conflict_files[repo_path]:
                conflict_repo = repo_path
                break
        
        if not conflict_repo:
            raise HTTPException(status_code=400, detail="没有找到有冲突的仓库")
        
        path = conflict_repo
    
    # 路径映射
    path = map_remote_path(path)
    
    result = resolve_conflicts(path, resolve_request.conflicts)
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@app.post("/api/v1/sync/clean")
def clean_sync_repo(path: Optional[str] = None, confirm: bool = False):
    """清理同步状态"""
    if not GIT_AVAILABLE:
        raise HTTPException(status_code=400, detail="Git功能不可用，请安装GitPython库")
    
    if not confirm:
        raise HTTPException(status_code=400, detail="必须确认清理操作")
    
    # 如果未指定路径，使用第一个仓库
    if not path:
        if not git_sync_info:
            raise HTTPException(status_code=400, detail="没有已初始化的Git仓库")
        path = next(iter(git_sync_info.keys()))
    
    # 路径映射
    path = map_remote_path(path)
    
    repo_path = Path(path)
    
    if not (repo_path / ".git").exists():
        raise HTTPException(status_code=400, detail="目标路径不是Git仓库")
    
    try:
        # 清理冲突记录
        if str(repo_path) in conflict_files:
            conflict_files[str(repo_path)] = []
        
        # 重置仓库状态
        repo = Repo(repo_path)
        repo.git.reset("--hard", "HEAD")
        repo.git.clean("-fd")
        
        # 更新同步信息
        if str(repo_path) in git_sync_info:
            git_sync_info[str(repo_path)]["last_sync"] = time.time()
        
        return {
            "status": "success",
            "message": "同步状态已清理"
        }
        
    except Exception as e:
        logger.error(f"清理同步状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清理同步状态失败: {str(e)}")


@app.post("/api/v1/files/mkdir")
async def create_directory(request: dict):
    """创建目录"""
    if "path" not in request:
        raise HTTPException(status_code=400, detail="缺少路径参数")
    
    path = request["path"]
    
    # 路径映射
    path = map_remote_path(path)
    
    dir_path = Path(path)
    
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"status": "success", "message": f"目录已创建: {dir_path}"}
    except PermissionError:
        logger.error(f"创建目录失败: 权限不足 {dir_path}")
        raise HTTPException(status_code=403, detail=f"创建目录失败: 权限不足 {dir_path}")
    except FileNotFoundError:
        logger.error(f"创建目录失败: 路径不存在 {dir_path}")
        raise HTTPException(status_code=404, detail=f"创建目录失败: 路径不存在 {dir_path}")
    except Exception as e:
        logger.error(f"创建目录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建目录失败: {str(e)}")
=======
@app.on_event("startup")
async def startup_event():
    logger.info("Server startup")
    await load_metadata_cache() # Load cache on startup

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Server shutting down")
    await save_metadata_cache() # Save cache on shutdown


async def load_metadata_cache():
    """Load file metadata cache from file"""
    global file_metadata_cache
    if CACHE_FILE.exists():
        try:
            async with aiofiles.open(CACHE_FILE, 'r', encoding='utf-8') as f:
                content = await f.read()
                file_metadata_cache = json.loads(content)
            logger.info(f"Metadata cache loaded from {CACHE_FILE}")
        except Exception as e:
            logger.error(f"Failed to load metadata cache from {CACHE_FILE}: {e}")
            file_metadata_cache = {} # Reset cache on error
    else:
        logger.info(f"Metadata cache file not found: {CACHE_FILE}. Starting with empty cache.")
        file_metadata_cache = {}

async def save_metadata_cache():
    """Save file metadata cache to file"""
    global file_metadata_cache
    try:
        # Ensure directory exists
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(CACHE_FILE, 'w', encoding='utf-8') as f:
            # Convert Pydantic models to dict before saving
            cache_data_to_save = {k: v if isinstance(v, dict) else v.model_dump() for k, v in file_metadata_cache.items()}
            await f.write(json.dumps(cache_data_to_save, indent=4))
        logger.info(f"Metadata cache saved to {CACHE_FILE}")
    except Exception as e:
        logger.error(f"Failed to save metadata cache to {CACHE_FILE}: {e}")
>>>>>>> f98f016 (修复增量同步失效问题)


# 如果作为主程序运行
if __name__ == "__main__":
    # 从命令行获取参数
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync-HTTP-MCP Remote Server")
    parser.add_argument("--port", type=int, default=8081, help="服务器端口")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="服务器主机地址")
    parser.add_argument("--test-mode", action="store_true", help="启用测试模式，将创建虚拟路径结构")
    parser.add_argument("--test-root", type=str, help="测试模式下的虚拟根目录，默认为用户主目录下的mcp_test_root")
    
    args = parser.parse_args()
    
    # 设置测试模式
    if args.test_mode:
        SERVER_CONFIG["test_mode"] = True
        logger.info("已启用测试模式")
        
        if args.test_root:
            SERVER_CONFIG["test_root_dir"] = args.test_root
        
        # 确保测试根目录存在
        test_root = Path(SERVER_CONFIG["test_root_dir"])
        test_root.mkdir(parents=True, exist_ok=True)
        
        # 创建基本目录结构
        home_dir = test_root / "home"
        home_dir.mkdir(exist_ok=True)
        
        logger.info(f"测试模式根目录: {test_root}")
    
    # 启动服务器
    uvicorn.run(app, host=args.host, port=args.port)