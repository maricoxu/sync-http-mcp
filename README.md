# Sync-HTTP-MCP

基于HTTP的远程代码同步和命令执行系统，支持块级增量同步和Git增量同步。

## 最新更新

### Git状态管理系统集成

现在已经完成了Git状态管理系统与服务器的集成，带来以下改进：

- **高效状态追踪**: 使用GitStateManager跟踪文件状态变化
- **持久化缓存**: 服务器端状态缓存持久化，重启后保持状态
- **路径映射优化**: 改进路径映射以更好地支持测试和生产环境
- **命令行控制**: 新增命令行选项控制Git缓存功能

## 快速开始

### 服务器启动

```bash
# 标准启动
python src/remote_server.py --host 0.0.0.0 --port 8081

# 带Git缓存配置的启动
python src/remote_server.py --host 0.0.0.0 --port 8081 --cache-dir ~/.mcp_git_cache

# 测试模式启动
python src/remote_server.py --host 0.0.0.0 --port 8081 --test-mode
```

### 客户端使用

```bash
# 使用Git同步方式 (默认)
python src/mcp_cli.py --server http://localhost:8081 --workspace ./local_dir sync

# 使用块级同步方式 
python src/mcp_cli.py --server http://localhost:8081 --workspace ./local_dir --block sync

# 初始化Git同步环境
python src/mcp_cli.py --server http://localhost:8081 --workspace ./local_dir git-init
```

## 新增命令行选项

服务器端新增命令行选项：

- `--cache-dir`: 设置Git状态缓存目录 (默认: ~/.mcp_cache)
- `--disable-git-cache`: 禁用Git状态缓存功能
- `--log-level`: 设置日志级别，可选值为DEBUG、INFO、WARNING、ERROR (默认: INFO)

## 测试

运行集成测试:

```bash
# 先启动服务器
python src/remote_server.py --host 0.0.0.0 --port 8081 --test-mode

# 运行测试
python tests/test_git_integration.py
```

## 功能特点

- 基于HTTP协议，支持多种网络环境
- 支持文件同步、远程命令执行等功能
- 支持增量同步，减少带宽占用
- **新增：支持基于Git的增量同步**，提供更高效的变更跟踪及冲突处理

## 依赖项

### 客户端依赖

```bash
pip install requests
```

### 服务器依赖

```bash
# 登录到内网服务器
relay-cli
ssh ${yourserver}

# Git同步功能依赖
pip install GitPython
```

## 安装说明

1. 克隆本仓库
2. 安装依赖项
3. 启动服务器和客户端

## 使用方法

### 服务器端

```bash
cd sync-http-mcp
python src/remote_server.py --port 8081 --host 0.0.0.0
```

### 客户端

**使用Git增量同步（推荐）：**

```bash
cd sync-http-mcp
python src/client.py sync --server http://server-ip:8081 --workspace /path/to/local/workspace
```

**使用传统块级增量同步：**

```bash
cd sync-http-mcp
python src/client.py --block sync --server http://server-ip:8081 --workspace /path/to/local/workspace
```

详细使用方法请参考 [使用说明文档](docs/USAGE.md)。

## 同步模式对比

| 特性 | Git增量同步(默认) | 块级增量同步 |
|------|--------------|-------------|
| 数据传输量 | 仅传输差异内容 | 传输变更的数据块 |
| 冲突处理 | 支持多种策略 | 基于时间戳 |
| 变更历史 | 完整保留 | 无历史记录 |
| 服务器要求 | 需要GitPython | 无特殊要求 |

## 注意事项

1. 首次同步时建议使用`sync`命令进行完整同步
2. 服务器需要确保对目标目录有读写权限
3. 如需使用Git增量同步功能，确保服务器已安装GitPython库