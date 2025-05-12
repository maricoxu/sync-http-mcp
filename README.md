# Sync-HTTP-MCP

基于HTTP的百度内部多云协同开发工具。

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