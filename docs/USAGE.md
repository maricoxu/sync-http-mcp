# Sync-HTTP-MCP 使用指南

本文档提供了Sync-HTTP-MCP简化版客户端的详细使用说明，包括安装、配置和使用方法。

## 特性

简化版客户端具有以下特点：

- **极简依赖**: 仅依赖`requests`和`websocket-client`两个库
- **同步操作**: 提供同步调用API
- **命令行工具**: 支持命令行方式使用
- **易于配置**: 最小化配置要求
- **可靠性**: 专注于稳定性和兼容性
- **增量同步**: 支持基于Git的增量同步，大幅提高传输效率和可靠性

## 安装步骤

### 1. 依赖安装

简化版客户端只需要非常基础的依赖：

```bash
# 安装基本依赖
pip install requests>=2.25.0 websocket-client>=1.0.0

# 可选：使用国内镜像加速安装
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests>=2.25.0 websocket-client>=1.0.0

# 可选：如需文件监控功能
pip install watchdog>=2.1.0

# 可选：如需图形界面
pip install PyQt5>=5.12.0
```

### 2. 验证安装

```bash
# 测试是否可以正常导入
python -c "import requests, websocket; print('依赖安装成功')"
```

### 3. 服务器端安装配置

#### 3.1 登录并配置服务器初始环境

```bash
# 通过webrelay或其他方式登录服务器
webrelay

# 或者使用传统登录方式
relay-cli
ssh bjhw-sys-rpm0221.bjhw.baidu.com
```

#### 3.2 配置Docker环境（推荐）

在服务器上使用Docker是最简单的部署方式：

```bash
# 下载并启动专用Docker镜像
docker pull reg.docker.alibaba-inc.com/paddle/sync-http-mcp:latest
docker run -d --name sync-http-mcp -p 8081:8081 -v /path/to/your/workspace:/workspace reg.docker.alibaba-inc.com/paddle/sync-http-mcp:latest
```

#### 3.3 手动配置服务器（备选）

如果不使用Docker，可以手动配置服务器：

```bash
# 克隆代码仓库
git clone https://github.com/your-username/sync-http-mcp.git
cd sync-http-mcp

# 安装服务器依赖
pip install -r server-requirements.txt

# 启动服务器
python src/remote_server.py
```

## 基本使用

### 1. 客户端命令行

#### 1.1 基本命令

```bash
# 同步文件到远程服务器
python src/client.py sync -w /path/to/local/workspace -s http://server-ip:8081

# 查看远程文件列表
python src/client.py list -s http://server-ip:8081 -p /remote/path

# 执行远程命令
python src/client.py exec -s http://server-ip:8081 -c "ls -la"
```

#### 1.2 使用默认参数

为简化命令，可以使用默认参数：

```bash
# 使用当前目录作为工作区，默认服务器地址
python src/client.py sync

# 等效于
python src/client.py sync -w $(pwd) -s http://localhost:8081
```

### 2. 客户端API

如果需要在自定义脚本中使用，可以导入客户端API：

```python
from client import Client

# 创建客户端实例
client = Client("http://server-ip:8081")

# 同步本地文件到远程
result = client.sync("/path/to/local/dir")
print(f"同步结果: {result}")

# 执行远程命令
output = client.execute_command("gcc -o main main.c")
print(f"命令输出: {output}")
```

## 增量同步功能（Git-based）

### 1. 概述

增量同步功能基于Git的diff/patch机制，相比传统文件块同步有如下优势：

- **极高效率**：只传输实际变更的内容，而不是整个文件或文件块
- **一致性保障**：利用Git成熟的补丁机制确保同步的可靠性
- **冲突处理**：提供冲突检测和多种解决策略
- **变更追踪**：每次同步点可作为版本记录，方便追溯

**注意：从最新版本开始，Git增量同步已成为默认同步方式。**

### 2. 统一命令行接口

所有Git增量同步功能已集成到主客户端命令中：

```bash
# 初始化Git同步环境（首次使用必须执行）
python src/client.py git-init

# 同步（默认使用Git增量同步）
python src/client.py sync

# 查看Git同步状态
python src/client.py git-status

# 解决冲突
python src/client.py git-resolve

# 如需使用块级增量同步
python src/client.py sync --block
# 或
python src/client.py --sync-mode block sync
```

原有的命令行使用方式仍然受支持，但建议使用新的统一接口：

```bash
# 旧命令 (不推荐)
python src/client_commands.py init
python src/client_commands.py sync
python src/client_commands.py status
python src/client_commands.py resolve

# 新命令 (推荐)
python src/client.py git-init
python src/client.py sync         # 默认使用Git增量同步
python src/client.py git-status
python src/client.py git-resolve
```

### 3. 初始化同步环境

首次使用增量同步功能，需要初始化本地和远程环境：

```bash
# 初始化同步环境
python src/client.py git-init

# 指定远程服务器上的路径
python src/client.py git-init --remote-path /home/yourproject

# 如果需要重新初始化，可以使用force选项
python src/client.py git-init --force
```

### 4. 执行增量同步

```bash
# 执行增量同步（默认使用Git模式）
python src/client.py sync

# 如需使用块级增量同步
python src/client.py sync --block

# 查看详细同步信息
python src/client.py sync -v
```

### 5. 查看同步状态

```bash
# 查看基本同步状态
python src/client.py git-status

# 查看详细状态，包括变更文件列表
python src/client.py git-status -v
```

### 6. 解决冲突

当远程和本地同时有变更时，可能会产生冲突：

```bash
# 交互式解决冲突（推荐）
python src/client.py git-resolve

# 使用本地版本解决所有冲突
python src/client.py git-resolve --strategy local

# 使用远程版本解决所有冲突
python src/client.py git-resolve --strategy remote
```

## 性能对比

下面是不同同步方式的性能对比：

| 同步方式 | 大型项目首次同步 | 小范围修改同步 | 冲突处理 | 一致性保障 |
|---------|--------------|------------|---------|---------|
| 完整传输 | 慢（100%传输） | 慢（100%传输） | 不支持 | 基本保障 |
| 块级增量 | 中（~100%传输） | 较快（~10-30%传输） | 有限支持 | 良好 |
| Git增量 | 中（~100%传输） | 极快（<1%传输） | 完整支持 | 优秀 |

## 高级功能

### 1. 连接多个远程服务器

如果需要在多个服务器间同步代码，可以使用不同的服务器地址：

```bash
# 同步到服务器A
python src/client.py -s http://server-a:8081 sync

# 同步到服务器B
python src/client.py -s http://server-b:8081 sync
```

### 2. 与现有Git工作流集成

增量同步功能不影响现有的Git使用：

```bash
# 使用Git管理代码版本
git add .
git commit -m "Feature implementation"

# 使用增量同步部署到远程服务器
python src/client.py sync
```

## 故障排除

### 1. 同步失败

如果同步失败，可尝试以下步骤：

1. 检查网络连接: `ping server-ip`
2. 验证服务器运行状态: `curl http://server-ip:8081/api/v1/status`
3. 查看详细日志: `python src/client_commands.py sync -v`
4. 重置同步状态: `python src/client_commands.py clean`

### 2. 冲突解决失败

1. 尝试使用`--strategy`选项选择特定的解决策略
2. 清理同步状态重新开始
3. 手动同步特定文件: `python src/client.py sync -f /path/to/file`

## 最佳实践

1. **定期同步**: 频繁进行小批量同步，而不是积累大量变更后一次同步
2. **合理组织工作区**: 避免包含大量二进制文件或临时文件
3. **使用`.gitignore`**: 配置适当的忽略规则，避免同步不必要的文件
4. **冲突解决策略**: 对于不同类型的文件，预先确定冲突解决策略

## 限制与注意事项

1. 增量同步基于Git机制，需要服务器安装Git（Docker镜像已包含）
2. 首次同步或大量变更时仍需完整传输，性能提升有限
3. 二进制文件的处理效率可能不如文本文件
4. 在极低带宽环境下，初始同步可能需要较长时间 