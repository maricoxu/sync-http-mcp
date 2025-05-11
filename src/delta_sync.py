#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sync-HTTP-MCP 增量同步模块

提供文件差异计算、元数据缓存和增量传输功能。
"""

import os
import json
import hashlib
import time
import base64
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_BLOCK_SIZE = 4096  # 4KB分块大小
DEFAULT_CACHE_FILE = ".mcp_cache.json"
DEFAULT_HASH_ALGORITHM = "md5"  # 可选: sha1, sha256等


class FileMetadata:
    """文件元数据类，存储文件的基本信息和块哈希值"""
    
    def __init__(self, path: str, mtime: float = 0, size: int = 0, 
                full_hash: str = "", blocks: Dict[int, str] = None):
        """
        初始化文件元数据
        
        Args:
            path: 文件路径
            mtime: 文件修改时间
            size: 文件大小(字节)
            full_hash: 文件完整哈希值
            blocks: 文件分块的哈希值字典 {块索引: 哈希值}
        """
        self.path = path
        self.mtime = mtime
        self.size = size
        self.full_hash = full_hash
        self.blocks = blocks or {}
    
    @classmethod
    def from_file(cls, file_path: str, block_size: int = DEFAULT_BLOCK_SIZE,
                algorithm: str = DEFAULT_HASH_ALGORITHM) -> 'FileMetadata':
        """
        从文件创建元数据
        
        Args:
            file_path: 文件路径
            block_size: 块大小(字节)
            algorithm: 哈希算法
            
        Returns:
            文件元数据对象
        """
        path_obj = Path(file_path)
        if not path_obj.exists() or not path_obj.is_file():
            raise FileNotFoundError(f"文件不存在或不是常规文件: {file_path}")
        
        stat = path_obj.stat()
        mtime = stat.st_mtime
        size = stat.st_size
        
        # 计算分块哈希值
        blocks = {}
        full_hasher = get_hasher(algorithm)
        
        with open(file_path, 'rb') as f:
            block_index = 0
            while True:
                data = f.read(block_size)
                if not data:
                    break
                
                # 更新完整文件哈希
                full_hasher.update(data)
                
                # 计算块哈希
                block_hasher = get_hasher(algorithm)
                block_hasher.update(data)
                blocks[block_index] = block_hasher.hexdigest()
                
                block_index += 1
        
        full_hash = full_hasher.hexdigest()
        
        return cls(str(path_obj), mtime, size, full_hash, blocks)
    
    def to_dict(self) -> Dict:
        """转换为字典表示"""
        return {
            "path": self.path,
            "mtime": self.mtime,
            "size": self.size,
            "full_hash": self.full_hash,
            "blocks": self.blocks
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FileMetadata':
        """从字典创建元数据对象"""
        return cls(
            path=data.get("path", ""),
            mtime=data.get("mtime", 0),
            size=data.get("size", 0),
            full_hash=data.get("full_hash", ""),
            blocks=data.get("blocks", {})
        )


class MetadataCache:
    """文件元数据缓存，管理本地和远程文件的元数据"""
    
    def __init__(self, cache_file: str = DEFAULT_CACHE_FILE):
        """
        初始化元数据缓存
        
        Args:
            cache_file: 缓存文件路径
        """
        self.cache_file = cache_file
        self.local_cache: Dict[str, FileMetadata] = {}
        self.remote_cache: Dict[str, FileMetadata] = {}
        self.load_cache()
    
    def load_cache(self) -> bool:
        """加载缓存文件"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                
                # 加载本地缓存
                local_data = data.get("local", {})
                for path, metadata in local_data.items():
                    self.local_cache[path] = FileMetadata.from_dict(metadata)
                
                # 加载远程缓存
                remote_data = data.get("remote", {})
                for path, metadata in remote_data.items():
                    self.remote_cache[path] = FileMetadata.from_dict(metadata)
                
                logger.info(f"已加载缓存: {len(self.local_cache)}个本地文件, "
                          f"{len(self.remote_cache)}个远程文件")
                return True
        except Exception as e:
            logger.error(f"加载缓存失败: {str(e)}")
            self.local_cache = {}
            self.remote_cache = {}
        
        return False
    
    def save_cache(self) -> bool:
        """保存缓存到文件"""
        try:
            # 转换为可序列化的字典
            local_dict = {path: meta.to_dict() for path, meta in self.local_cache.items()}
            remote_dict = {path: meta.to_dict() for path, meta in self.remote_cache.items()}
            
            data = {
                "local": local_dict,
                "remote": remote_dict
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"缓存已保存: {self.cache_file}")
            return True
        except Exception as e:
            logger.error(f"保存缓存失败: {str(e)}")
            return False
    
    def update_local_metadata(self, file_path: str, block_size: int = DEFAULT_BLOCK_SIZE) -> FileMetadata:
        """
        更新本地文件元数据
        
        Args:
            file_path: 文件路径
            block_size: 块大小
            
        Returns:
            文件元数据
        """
        try:
            metadata = FileMetadata.from_file(file_path, block_size)
            self.local_cache[metadata.path] = metadata
            return metadata
        except Exception as e:
            logger.error(f"更新本地元数据失败: {file_path} - {str(e)}")
            raise
    
    def update_remote_metadata(self, metadata: FileMetadata) -> None:
        """
        更新远程文件元数据
        
        Args:
            metadata: 文件元数据
        """
        self.remote_cache[metadata.path] = metadata
    
    def get_local_metadata(self, file_path: str) -> Optional[FileMetadata]:
        """获取本地文件元数据"""
        return self.local_cache.get(str(Path(file_path).resolve()), None)
    
    def get_remote_metadata(self, file_path: str) -> Optional[FileMetadata]:
        """获取远程文件元数据"""
        return self.remote_cache.get(file_path, None)
    
    def clean_up(self, local_base_path: Optional[str] = None, 
               remote_base_path: Optional[str] = None) -> int:
        """
        清理不存在文件的缓存
        
        Args:
            local_base_path: 本地基础路径，如果提供则只清理该路径下的缓存
            remote_base_path: 远程基础路径，如果提供则只清理该路径下的缓存
            
        Returns:
            清理的缓存项数量
        """
        count = 0
        
        # 清理本地缓存
        if local_base_path:
            local_base = str(Path(local_base_path).resolve())
            to_remove = []
            for path in self.local_cache:
                if path.startswith(local_base):
                    if not os.path.exists(path):
                        to_remove.append(path)
            
            for path in to_remove:
                del self.local_cache[path]
                count += 1
        
        # 清理远程缓存 (仅根据路径前缀)
        if remote_base_path:
            to_remove = []
            for path in self.remote_cache:
                if path.startswith(remote_base_path):
                    # 这里我们无法检查远程文件是否存在，只能根据路径前缀清理
                    to_remove.append(path)
            
            for path in to_remove:
                del self.remote_cache[path]
                count += 1
        
        logger.info(f"清理缓存: 移除了{count}个过期项")
        return count


class DeltaSyncCalculator:
    """增量同步计算器，计算文件变更和需要传输的块"""
    
    def __init__(self, cache: MetadataCache, block_size: int = DEFAULT_BLOCK_SIZE):
        """
        初始化增量同步计算器
        
        Args:
            cache: 元数据缓存对象
            block_size: 块大小(字节)
        """
        self.cache = cache
        self.block_size = block_size
    
    def calculate_delta(self, local_path: str, remote_path: str) -> Dict:
        """
        计算本地文件与远程文件的差异
        
        Args:
            local_path: 本地文件路径
            remote_path: 远程文件路径
            
        Returns:
            差异信息字典
        """
        # 获取或更新本地文件元数据
        try:
            local_meta = self.cache.get_local_metadata(local_path)
            if not local_meta or not os.path.exists(local_path) or \
               os.path.getmtime(local_path) > local_meta.mtime:
                local_meta = self.cache.update_local_metadata(local_path, self.block_size)
        except Exception as e:
            logger.error(f"获取本地文件元数据失败: {str(e)}")
            return {
                "type": "full",  # 如果无法获取本地元数据，执行完整传输
                "full_hash": "",
                "size": 0,
                "blocks": []
            }
        
        # 获取远程文件元数据
        remote_meta = self.cache.get_remote_metadata(remote_path)
        
        # 如果没有远程元数据或哈希不匹配，需要完整传输
        if not remote_meta or remote_meta.full_hash != local_meta.full_hash:
            if not remote_meta:
                logger.info(f"远程文件无缓存: {remote_path}")
            else:
                logger.info(f"文件已变更: {local_path} -> {remote_path}")
                logger.debug(f"本地哈希: {local_meta.full_hash}, 远程哈希: {remote_meta.full_hash}")
            
            # 计算需要传输的块索引
            changed_blocks = list(range(len(local_meta.blocks)))
            
            return {
                "type": "delta" if remote_meta else "full",
                "full_hash": local_meta.full_hash,
                "size": local_meta.size,
                "blocks": changed_blocks
            }
        
        # 文件相同，无需传输
        if remote_meta.full_hash == local_meta.full_hash:
            logger.info(f"文件未变更: {local_path} -> {remote_path}")
            return {
                "type": "none",
                "full_hash": local_meta.full_hash,
                "size": local_meta.size,
                "blocks": []
            }
    
    def extract_blocks(self, file_path: str, block_indices: List[int]) -> Dict[int, bytes]:
        """
        从文件中提取指定的数据块
        
        Args:
            file_path: 文件路径
            block_indices: 块索引列表
            
        Returns:
            块索引到数据的映射字典
        """
        blocks = {}
        
        with open(file_path, 'rb') as f:
            for block_index in block_indices:
                f.seek(block_index * self.block_size)
                data = f.read(self.block_size)
                if data:  # 如果读取到数据
                    blocks[block_index] = data
        
        return blocks


def get_hasher(algorithm: str = DEFAULT_HASH_ALGORITHM):
    """
    获取指定算法的哈希计算器
    
    Args:
        algorithm: 哈希算法名称
        
    Returns:
        哈希计算器对象
    """
    if algorithm == "md5":
        return hashlib.md5()
    elif algorithm == "sha1":
        return hashlib.sha1()
    elif algorithm == "sha256":
        return hashlib.sha256()
    else:
        raise ValueError(f"不支持的哈希算法: {algorithm}")


def create_delta_payload(local_path: str, remote_path: str, delta_info: Dict) -> Dict:
    """
    创建增量同步负载
    
    Args:
        local_path: 本地文件路径
        remote_path: 远程文件路径
        delta_info: 差异信息
        
    Returns:
        用于传输的负载数据
    """
    payload = {
        "path": remote_path,
        "delta_type": delta_info["type"],
        "full_hash": delta_info["full_hash"],
        "size": delta_info["size"],
    }
    
    # 如果不需要传输数据，直接返回
    if delta_info["type"] == "none":
        return payload
    
    # 提取需要传输的块数据
    if delta_info["blocks"]:
        calculator = DeltaSyncCalculator(MetadataCache())
        blocks = calculator.extract_blocks(local_path, delta_info["blocks"])
        
        # 编码块数据
        encoded_blocks = {}
        for index, data in blocks.items():
            encoded_blocks[str(index)] = base64.b64encode(data).decode('utf-8')
        
        payload["blocks"] = encoded_blocks
    
    # 如果是完整传输，添加完整文件内容
    if delta_info["type"] == "full" and "blocks" not in payload:
        with open(local_path, 'rb') as f:
            content = f.read()
            payload["content"] = base64.b64encode(content).decode('utf-8')
    
    return payload


# 测试代码
if __name__ == "__main__":
    import tempfile
    import shutil
    
    # 创建测试目录和文件
    test_dir = tempfile.mkdtemp()
    try:
        # 创建测试文件
        test_file = os.path.join(test_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("This is a test file.\n" * 1000)
        
        # 测试元数据计算
        metadata = FileMetadata.from_file(test_file)
        print(f"文件大小: {metadata.size} 字节")
        print(f"哈希值: {metadata.full_hash}")
        print(f"块数: {len(metadata.blocks)}")
        
        # 测试缓存
        cache = MetadataCache(os.path.join(test_dir, ".cache.json"))
        cache.update_local_metadata(test_file)
        cache.save_cache()
        
        # 修改文件
        with open(test_file, 'a') as f:
            f.write("Added new content.\n")
        
        # 计算差异
        calculator = DeltaSyncCalculator(cache)
        delta = calculator.calculate_delta(test_file, "/remote/test.txt")
        print(f"差异类型: {delta['type']}")
        print(f"变更块数: {len(delta['blocks'])}")
        
        # 创建负载
        payload = create_delta_payload(test_file, "/remote/test.txt", delta)
        print(f"负载大小: {len(str(payload))} 字节")
        
    finally:
        # 清理测试目录
        shutil.rmtree(test_dir) 