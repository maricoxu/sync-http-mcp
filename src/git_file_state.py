#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Git同步文件状态模块

提供文件状态表示、Git状态转换和元数据生成功能。
"""

import os
import hashlib
import time
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple, Any

import logging
logger = logging.getLogger(__name__)


class GitFileState:
    """Git文件状态，表示文件在Git环境下的状态信息"""
    
    # Git状态类型
    STATUS_UNMODIFIED = "unmodified"  # 未修改
    STATUS_MODIFIED = "modified"      # 已修改
    STATUS_ADDED = "added"            # 新增
    STATUS_DELETED = "deleted"        # 已删除
    STATUS_RENAMED = "renamed"        # 已重命名 
    STATUS_COPIED = "copied"          # 已复制
    STATUS_UNTRACKED = "untracked"    # 未跟踪
    STATUS_IGNORED = "ignored"        # 被忽略
    STATUS_CONFLICT = "conflict"      # 冲突
    
    def __init__(self, path: str, mtime: float = 0, size: int = 0,
                content_hash: str = "", git_status: str = STATUS_UNTRACKED,
                sync_timestamp: float = 0, original_path: Optional[str] = None):
        """
        初始化Git文件状态
        
        Args:
            path: 文件相对路径
            mtime: 文件修改时间
            size: 文件大小（字节）
            content_hash: 文件内容哈希值
            git_status: Git状态码
            sync_timestamp: 上次同步时间戳
            original_path: 原始路径（适用于重命名情况）
        """
        self.path = path
        self.mtime = mtime
        self.size = size
        self.content_hash = content_hash
        self.git_status = git_status
        self.sync_timestamp = sync_timestamp
        self.original_path = original_path
    
    @classmethod
    def from_file(cls, file_path: str, base_dir: Optional[str] = None, 
                git_status: Optional[str] = None) -> 'GitFileState':
        """
        从文件创建状态对象
        
        Args:
            file_path: 文件路径
            base_dir: 基础目录，用于计算相对路径
            git_status: Git状态，如果已知
            
        Returns:
            GitFileState对象
        """
        path_obj = Path(file_path)
        
        # 计算相对路径
        if base_dir:
            try:
                rel_path = str(path_obj.relative_to(base_dir))
            except ValueError:
                rel_path = str(path_obj)
        else:
            rel_path = str(path_obj)
        
        # 获取文件基本信息
        if path_obj.exists() and path_obj.is_file():
            stat = path_obj.stat()
            mtime = stat.st_mtime
            size = stat.st_size
            content_hash = cls.calculate_file_hash(file_path)
            if not git_status:
                git_status = cls.STATUS_UNTRACKED
        else:
            # 文件不存在，可能是已删除
            mtime = 0
            size = 0
            content_hash = ""
            if not git_status:
                git_status = cls.STATUS_DELETED
        
        return cls(
            path=rel_path,
            mtime=mtime,
            size=size,
            content_hash=content_hash,
            git_status=git_status,
            sync_timestamp=time.time()
        )
    
    @staticmethod
    def calculate_file_hash(file_path: str, algorithm: str = "md5") -> str:
        """
        计算文件哈希值
        
        Args:
            file_path: 文件路径
            algorithm: 哈希算法（默认md5）
            
        Returns:
            文件哈希值的十六进制字符串
        """
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            return ""
        
        hasher = hashlib.new(algorithm)
        
        try:
            with open(file_path, 'rb') as f:
                # 对大文件分块读取
                chunk_size = 4096  # 4KB块
                while True:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    hasher.update(data)
            
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"计算文件哈希值出错: {file_path} - {str(e)}")
            return ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典表示"""
        result = {
            "path": self.path,
            "mtime": self.mtime,
            "size": self.size,
            "content_hash": self.content_hash,
            "git_status": self.git_status,
            "sync_timestamp": self.sync_timestamp
        }
        
        if self.original_path:
            result["original_path"] = self.original_path
            
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GitFileState':
        """从字典创建GitFileState对象"""
        return cls(
            path=data.get("path", ""),
            mtime=data.get("mtime", 0),
            size=data.get("size", 0),
            content_hash=data.get("content_hash", ""),
            git_status=data.get("git_status", cls.STATUS_UNTRACKED),
            sync_timestamp=data.get("sync_timestamp", 0),
            original_path=data.get("original_path")
        )
    
    def has_same_content(self, other: 'GitFileState') -> bool:
        """检查是否具有相同内容"""
        if not other:
            return False
        
        # 如果有内容哈希，优先使用哈希比较
        if self.content_hash and other.content_hash:
            return self.content_hash == other.content_hash
        
        # 否则使用大小和修改时间
        return self.size == other.size and self.mtime == other.mtime
    
    def needs_sync(self, other: Optional['GitFileState'] = None) -> bool:
        """
        判断是否需要同步
        
        Args:
            other: 另一个GitFileState对象（如远程文件状态）
            
        Returns:
            是否需要同步
        """
        # 如果没有远程状态，则需要同步
        if not other:
            return self.git_status != self.STATUS_IGNORED
        
        # 忽略的文件不同步
        if self.git_status == self.STATUS_IGNORED:
            return False
        
        # 文件路径不同（可能是重命名）
        if self.path != other.path:
            return True
        
        # 删除状态检查
        if self.git_status == self.STATUS_DELETED or other.git_status == self.STATUS_DELETED:
            return self.git_status != other.git_status
        
        # 内容变化检查
        return not self.has_same_content(other)
    
    def __eq__(self, other):
        """判断两个状态是否相等"""
        if not isinstance(other, GitFileState):
            return False
        
        return (self.path == other.path and
                self.content_hash == other.content_hash and
                self.git_status == other.git_status)
    
    def __str__(self):
        """字符串表示"""
        status_str = self.git_status.upper() if self.git_status else "UNKNOWN"
        return f"[{status_str}] {self.path} ({self.size} bytes, modified: {self.mtime})"


class GitStateManager:
    """Git文件状态管理器，管理文件状态缓存和Git状态转换"""
    
    def __init__(self, base_dir: str, cache_file: Optional[str] = None):
        """
        初始化Git状态管理器
        
        Args:
            base_dir: 基础目录
            cache_file: 缓存文件路径（如果不提供，则使用内存缓存）
        """
        self.base_dir = Path(base_dir).resolve()
        self.cache_file = cache_file
        self.file_states: Dict[str, GitFileState] = {}
        self.last_sync_timestamp = 0
        
        # 如果提供了缓存文件，则加载
        if cache_file and os.path.exists(cache_file):
            self.load_cache()
    
    def get_file_state(self, file_path: str) -> Optional[GitFileState]:
        """获取文件状态，如果不存在则返回None"""
        path_obj = Path(file_path)
        
        # 计算相对路径
        try:
            rel_path = str(path_obj.relative_to(self.base_dir))
        except ValueError:
            rel_path = str(path_obj)
        
        return self.file_states.get(rel_path)
    
    def update_file_state(self, file_path: str, git_status: Optional[str] = None) -> GitFileState:
        """更新文件状态"""
        path_obj = Path(file_path)
        
        # 计算相对路径
        try:
            rel_path = str(path_obj.relative_to(self.base_dir))
        except ValueError:
            rel_path = str(path_obj)
        
        state = GitFileState.from_file(file_path, self.base_dir, git_status)
        self.file_states[rel_path] = state
        return state
    
    def remove_file_state(self, file_path: str) -> bool:
        """移除文件状态"""
        path_obj = Path(file_path)
        
        # 计算相对路径
        try:
            rel_path = str(path_obj.relative_to(self.base_dir))
        except ValueError:
            rel_path = str(path_obj)
        
        if rel_path in self.file_states:
            del self.file_states[rel_path]
            return True
        return False
    
    def scan_directory(self, directory: Optional[str] = None, 
                      ignore_patterns: Optional[List[str]] = None) -> Dict[str, GitFileState]:
        """
        扫描目录，更新文件状态
        
        Args:
            directory: 要扫描的目录（默认为基础目录）
            ignore_patterns: 要忽略的文件模式列表
            
        Returns:
            文件状态字典 {相对路径: GitFileState}
        """
        scan_dir = directory or self.base_dir
        path_obj = Path(scan_dir)
        result = {}
        
        # 递归扫描目录
        for root, dirs, files in os.walk(path_obj):
            # 跳过.git目录
            if '.git' in dirs:
                dirs.remove('.git')
            
            # 处理文件
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.base_dir)
                
                # 检查是否忽略
                if ignore_patterns and any(rel_path.startswith(p) for p in ignore_patterns):
                    continue
                
                state = self.update_file_state(file_path)
                result[rel_path] = state
        
        return result
    
    def update_from_git_status(self, git_status_output: str) -> Dict[str, GitFileState]:
        """
        从Git状态输出更新文件状态
        
        Args:
            git_status_output: git status --porcelain 的输出
            
        Returns:
            更新的文件状态字典
        """
        updated_states = {}
        
        for line in git_status_output.splitlines():
            if not line or len(line) < 3:
                continue
            
            status_code = line[:2]
            file_path = line[3:].strip()
            
            # 处理重命名情况 "R file1 -> file2"
            if status_code.startswith('R'):
                if ' -> ' in file_path:
                    old_path, new_path = file_path.split(' -> ', 1)
                    full_path = os.path.join(self.base_dir, new_path)
                    state = self.update_file_state(full_path, GitFileState.STATUS_RENAMED)
                    state.original_path = old_path
                    updated_states[new_path] = state
                continue
            
            full_path = os.path.join(self.base_dir, file_path)
            git_status = self._parse_git_status_code(status_code)
            state = self.update_file_state(full_path, git_status)
            updated_states[file_path] = state
        
        return updated_states
    
    def _parse_git_status_code(self, status_code: str) -> str:
        """解析Git状态码"""
        # 第一列：暂存区状态
        # 第二列：工作区状态
        index_status = status_code[0]
        worktree_status = status_code[1]
        
        # 解析状态
        if index_status == '?' and worktree_status == '?':
            return GitFileState.STATUS_UNTRACKED
        elif index_status == '!' and worktree_status == '!':
            return GitFileState.STATUS_IGNORED
        elif worktree_status == 'M':
            return GitFileState.STATUS_MODIFIED
        elif index_status == 'A':
            return GitFileState.STATUS_ADDED
        elif index_status == 'D' or worktree_status == 'D':
            return GitFileState.STATUS_DELETED
        elif index_status == 'R':
            return GitFileState.STATUS_RENAMED
        elif index_status == 'C':
            return GitFileState.STATUS_COPIED
        elif index_status == 'U' or worktree_status == 'U':
            return GitFileState.STATUS_CONFLICT
        
        return GitFileState.STATUS_UNMODIFIED
    
    def load_cache(self) -> bool:
        """加载缓存文件"""
        if not self.cache_file or not os.path.exists(self.cache_file):
            return False
        
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
            
            self.last_sync_timestamp = data.get('last_sync_timestamp', 0)
            
            # 加载文件状态
            files_data = data.get('files', {})
            self.file_states = {}
            
            for path, state_data in files_data.items():
                self.file_states[path] = GitFileState.from_dict(state_data)
            
            logger.info(f"已加载Git状态缓存: {len(self.file_states)}个文件")
            return True
        
        except Exception as e:
            logger.error(f"加载Git状态缓存失败: {str(e)}")
            self.file_states = {}
            self.last_sync_timestamp = 0
        
        return False
    
    def save_cache(self) -> bool:
        """保存缓存到文件"""
        if not self.cache_file:
            return False
        
        try:
            # 转换为可序列化的字典
            files_dict = {path: state.to_dict() for path, state in self.file_states.items()}
            
            data = {
                'last_sync_timestamp': self.last_sync_timestamp,
                'files': files_dict
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Git状态缓存已保存: {self.cache_file}")
            return True
        
        except Exception as e:
            logger.error(f"保存Git状态缓存失败: {str(e)}")
            return False
    
    def update_sync_timestamp(self, timestamp: Optional[float] = None) -> None:
        """更新同步时间戳"""
        self.last_sync_timestamp = timestamp or time.time()
    
    def get_modified_since_last_sync(self) -> Dict[str, GitFileState]:
        """获取自上次同步以来修改的文件"""
        result = {}
        
        for path, state in self.file_states.items():
            # 如果文件的修改时间晚于上次同步时间，或者状态表明需要同步
            if state.mtime > self.last_sync_timestamp or state.git_status in [
                GitFileState.STATUS_MODIFIED, 
                GitFileState.STATUS_ADDED,
                GitFileState.STATUS_DELETED,
                GitFileState.STATUS_RENAMED,
                GitFileState.STATUS_COPIED,
                GitFileState.STATUS_UNTRACKED
            ]:
                result[path] = state
        
        return result
    
    def compare_states(self, remote_states: Dict[str, GitFileState]) -> Dict[str, str]:
        """
        比较本地和远程文件状态
        
        Args:
            remote_states: 远程文件状态字典
            
        Returns:
            状态比较结果 {文件路径: 状态描述}
        """
        result = {}
        
        # 检查本地文件在远程的状态
        for local_path, local_state in self.file_states.items():
            remote_state = remote_states.get(local_path)
            
            if not remote_state:
                # 远程不存在该文件
                if local_state.git_status == GitFileState.STATUS_DELETED:
                    result[local_path] = "双方都已删除"
                else:
                    result[local_path] = "本地新增"
            elif local_state.git_status == GitFileState.STATUS_DELETED:
                result[local_path] = "本地已删除"
            elif remote_state.git_status == GitFileState.STATUS_DELETED:
                result[local_path] = "远程已删除"
            elif not local_state.has_same_content(remote_state):
                if local_state.sync_timestamp > remote_state.sync_timestamp:
                    result[local_path] = "本地更新"
                elif local_state.sync_timestamp < remote_state.sync_timestamp:
                    result[local_path] = "远程更新"
                else:
                    result[local_path] = "冲突"
            else:
                result[local_path] = "相同"
        
        # 检查远程独有的文件
        for remote_path, remote_state in remote_states.items():
            if remote_path not in self.file_states and remote_state.git_status != GitFileState.STATUS_DELETED:
                result[remote_path] = "远程新增"
        
        return result


# 测试代码
if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # 测试基本功能
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cache_file = os.path.join(base_dir, "git_state_test.json")
    
    manager = GitStateManager(base_dir, cache_file)
    
    # 扫描目录
    print("扫描目录...")
    states = manager.scan_directory()
    print(f"找到 {len(states)} 个文件")
    
    # 打印几个文件状态
    for i, (path, state) in enumerate(states.items()):
        print(f"{i+1}. {state}")
        if i >= 4:  # 只显示前5个
            break
    
    # 保存缓存
    manager.save_cache()
    print(f"缓存已保存到: {cache_file}")