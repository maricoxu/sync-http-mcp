# Git同步系统设计文档

## 概述

本文档描述了基于Git机制的文件同步系统设计。该系统旨在提供高效的增量同步功能，利用Git的差异比较和文件状态跟踪能力，实现客户端和服务器间的文件同步。

## 设计目标

1. 提供基于Git机制的高效增量同步
2. 支持.gitignore规则过滤不需要同步的文件
3. 实现服务器端文件状态缓存的持久化
4. 优化同步流程，减少网络传输量
5. 提供简单清晰的用户接口

## 系统架构

系统由客户端和服务器两部分组成：

- **客户端**：负责本地文件状态管理、差异计算和用户交互
- **服务器**：负责远程文件管理、状态缓存和请求处理

通信采用HTTP协议，使用JSON格式交换数据。

## 核心组件设计

### 1. 文件状态表示（File State Representation）

每个文件的状态由以下字段表示：

| 字段 | 类型 | 描述 |
|------|------|------|
| path | string | 文件相对路径 |
| mtime | float | 文件最后修改时间 |
| size | integer | 文件大小（字节） |
| content_hash | string | 文件内容的哈希值 |
| git_status | string | Git状态（modified/new/deleted/untracked等） |
| sync_timestamp | float | 最后同步时间 |

```python
class FileMetadata:
    def __init__(self, path, mtime, size, content_hash, git_status, sync_timestamp):
        self.path = path
        self.mtime = mtime
        self.size = size
        self.content_hash = content_hash
        self.git_status = git_status
        self.sync_timestamp = sync_timestamp
```

### 2. 客户端-服务器通信协议

#### 同步命令

| 命令 | 描述 | 参数 |
|------|------|------|
| git-init | 初始化Git同步环境 | target_dir, options |
| git-status | 获取文件同步状态 | target_dir |
| sync | 执行文件同步 | target_dir, options |
| git-resolve | 解决同步冲突 | target_dir, resolution_strategy |

#### 请求格式

```json
{
  "command": "sync",
  "target_dir": "/path/to/dir",
  "options": {
    "force": false,
    "ignore_errors": false
  }
}
```

#### 响应格式

```json
{
  "status": "success",
  "data": {
    "files_processed": 10,
    "files_synced": 3,
    "sync_details": [...]
  },
  "error": null
}
```

### 3. 同步操作流程

#### 初始化流程 (git-init)

1. 客户端检查本地目录，初始化Git仓库（如需要）
2. 服务器初始化目标目录的状态缓存
3. 建立初始同步点

#### 状态检查流程 (git-status)

1. 客户端获取本地文件状态
2. 请求服务器端文件状态
3. 比对两端状态，生成状态报告

#### 同步流程 (sync)

1. 获取上次同步点以来的变更
2. 生成差异补丁
3. 发送补丁到服务器
4. 服务器应用补丁
5. 更新双方同步状态
6. 处理潜在冲突

#### 冲突解决流程 (git-resolve)

1. 获取冲突文件列表
2. 根据策略生成解决方案
3. 应用解决方案
4. 更新同步状态

### 4. 状态缓存设计

#### 缓存数据结构

```json
{
  "last_sync_timestamp": 1621234567.89,
  "files": {
    "/path/to/file1.txt": {
      "path": "/path/to/file1.txt",
      "mtime": 1621234560.0,
      "size": 1024,
      "content_hash": "a1b2c3d4...",
      "git_status": "tracked",
      "sync_timestamp": 1621234567.89
    },
    ...
  }
}
```

#### 持久化机制

- 缓存保存为JSON文件
- 位置策略：
  - 默认：服务器脚本所在目录
  - 可配置：通过环境变量或命令行参数
  - 按目标：为每个同步目标维护单独的缓存文件

#### 缓存更新时机

- 服务器启动时加载
- 文件变更后更新
- 同步操作完成后更新
- 服务器关闭时保存

### 5. .gitignore集成

#### 解析机制

使用`pathspec`库解析.gitignore文件规则，服务器启动时加载规则。

```python
import pathspec

def load_gitignore(gitignore_path):
    with open(gitignore_path) as f:
        spec = pathspec.PathSpec.from_lines('gitwildmatch', f)
    return spec

def is_ignored(file_path, spec):
    return spec.match_file(file_path)
```

#### 应用规则

在以下环节应用过滤规则：
- 文件列表生成阶段
- 状态比较阶段
- 同步操作前检查

### 6. 冲突检测与解决

#### 冲突定义

当本地和服务器端的同一文件在上次同步后均有修改，且修改内容不同时，视为冲突。

#### 冲突解决策略

- 客户端优先：使用客户端版本覆盖服务器版本
- 服务器优先：保留服务器版本，丢弃客户端修改
- 合并：尝试自动合并变更（适用于文本文件）
- 重命名：保留双方版本，客户端版本使用新名称

## 实现计划

### 第一阶段：基础框架

1. 定义文件状态表示类
2. 实现客户端和服务器的基本通信框架
3. 设计并实现缓存机制

### 第二阶段：Git集成

1. 开发Git操作封装
2. 实现diff生成和应用
3. 实现.gitignore解析和过滤

### 第三阶段：同步功能

1. 实现同步点管理
2. 开发增量同步逻辑
3. 添加冲突检测和基本解决策略

### 第四阶段：优化和完善

1. 优化性能和资源使用
2. 增强错误处理和异常恢复
3. 完善日志和调试功能
4. 增加高级功能（如合并策略）

## 测试策略

1. 单元测试：验证各组件独立功能
2. 集成测试：验证组件间交互
3. 场景测试：模拟典型使用场景
4. 性能测试：评估同步效率和资源消耗
5. 故障恢复测试：验证系统从异常状态恢复的能力