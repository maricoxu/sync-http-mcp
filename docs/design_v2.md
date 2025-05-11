# Sync-HTTP-MCP 设计文档 (直接部署版)

## 1. 项目概述

### 1.1 背景

百度内部开发环境需要通过relay-cli跳板机连接，传统SSH连接方式无法直接与内部服务器建立持久可靠的连接。开发人员需要一种可靠的方式在本地IDE（如Cursor）中编辑代码，并在远程服务器上进行同步、编译、测试等操作。

### 1.2 目标

设计并实现一个基于HTTP协议的服务，直接部署在百度内网服务器上，通过简单的端口转发实现本地IDE与内网服务器之间的无缝连接，支持文件同步、远程编译、日志查看等功能，提高开发效率。

### 1.3 核心价值

- 消除开发环境障碍，实现真正的"本地开发，远程编译"
- 保留本地IDE的全部功能，同时获得远程服务器的强大算力
- 自动化流程，减少手动操作，提高开发效率
- 简化架构，减少中间层，提高稳定性和性能

## 2. 系统架构

### 2.1 整体架构

系统由两个主要部分组成：

1. **本地客户端（Local Client）**
   - 集成到Cursor IDE
   - 监控本地文件变化
   - 发送文件同步请求
   - 展示编译状态和日志

2. **内网HTTP服务器（Remote HTTP Server）**
   - 部署在百度内网服务器上
   - 提供文件系统访问API
   - 执行编译和测试命令
   - 收集并返回日志和状态

### 2.2 架构图

```
┌─────────────────┐       端口转发隧道       ┌────────────────────┐
│                 │                         │                    │
│  Local Client   │◄────────HTTP/WS────────►│  Remote HTTP Server │
│   (Cursor IDE)  │                         │  (百度内网服务器)     │
│                 │                         │                    │
└─────────────────┘                         └────────────────────┘
                                                      │
                                                      ▼
                                            ┌────────────────────┐
                                            │   文件系统 & 命令执行  │
                                            └────────────────────┘
```

### 2.3 通信流程

```
┌─────────┐          ┌─────────┐          ┌─────────┐
│ 用户操作  │─────────►│ 一次性设置 │─────────►│relay-cli │
└─────────┘          │端口转发隧道│          └─────────┘
                     └─────────┘               │
                                              │
┌─────────┐          ┌─────────┐          ┌─────────┐
│ IDE请求  │◄─────────►│ HTTP/WS │◄─────────►│ 内网服务器│
└─────────┘          │  隧道   │          │HTTP服务 │
                     └─────────┘          └─────────┘
```

## 3. 技术选型

### 3.1 客户端

- **语言/框架**: TypeScript + Electron（Cursor插件）
- **核心库**: 
  - `chokidar`: 文件监控
  - `axios`: HTTP请求
  - `socket.io-client`: WebSocket通信
  - `diff`: 差量更新计算

### 3.2 服务器端

- **语言/框架**: Python + FastAPI
- **核心库**:
  - `asyncio`: 异步IO处理
  - `websockets`: WebSocket支持
  - `aiofiles`: 异步文件操作
  - `subprocess`: 命令执行
  - `watchdog`: 文件系统监控

## 4. 核心功能与API设计

### 4.1 文件操作

#### 4.1.1 获取文件列表

```
GET /api/v1/files?path=/home/user/project
Response:
{
  "files": [
    {
      "name": "main.cpp",
      "path": "/home/user/project/main.cpp",
      "type": "file",
      "size": 1024,
      "last_modified": "2023-04-25T10:15:30Z"
    },
    {
      "name": "lib",
      "path": "/home/user/project/lib",
      "type": "directory"
    }
  ]
}
```

#### 4.1.2 获取文件内容

```
GET /api/v1/files/content?path=/home/user/project/main.cpp
Response:
{
  "content": "base64_encoded_content",
  "path": "/home/user/project/main.cpp",
  "last_modified": "2023-04-25T10:15:30Z",
  "checksum": "md5_hash"
}
```

#### 4.1.3 更新/创建文件

```
PUT /api/v1/files/content
Request:
{
  "path": "/home/user/project/main.cpp",
  "content": "base64_encoded_content",
  "checksum": "md5_hash"
}

Response:
{
  "status": "success",
  "path": "/home/user/project/main.cpp",
  "last_modified": "2023-04-25T10:20:45Z"
}
```

#### 4.1.4 批量同步文件

```
POST /api/v1/files/sync
Request:
{
  "files": [
    {
      "path": "src/main.cpp",
      "content": "base64_encoded_content",
      "checksum": "md5_hash"
    }
  ]
}

Response:
{
  "status": "success",
  "synchronized": 1,
  "failed": 0,
  "details": [
    {
      "path": "src/main.cpp",
      "status": "success"
    }
  ]
}
```

### 4.2 命令执行

#### 4.2.1 执行命令

```
POST /api/v1/commands
Request:
{
  "command": "make all",
  "working_directory": "/home/user/project",
  "environment": {
    "DEBUG": "1"
  },
  "timeout": 300
}

Response:
{
  "command_id": "cmd_9876543210",
  "status": "started",
  "start_time": "2023-04-25T10:25:00Z"
}
```

#### 4.2.2 获取命令状态

```
GET /api/v1/commands/{command_id}
Response:
{
  "command_id": "cmd_9876543210",
  "status": "completed",
  "start_time": "2023-04-25T10:25:00Z",
  "end_time": "2023-04-25T10:26:30Z",
  "exit_code": 0,
  "output_url": "/api/v1/commands/{command_id}/output"
}
```

#### 4.2.3 获取命令输出

```
GET /api/v1/commands/{command_id}/output
Response:
{
  "output": "命令输出内容...",
  "is_complete": true
}
```

### 4.3 WebSocket事件

#### 4.3.1 文件变更通知

```
{
  "type": "file_changed",
  "data": {
    "path": "/home/user/project/main.cpp",
    "operation": "modified",
    "timestamp": "2023-04-25T10:30:15Z"
  }
}
```

#### 4.3.2 命令状态更新

```
{
  "type": "command_status",
  "data": {
    "command_id": "cmd_9876543210",
    "status": "running",
    "output_chunk": "新的输出内容片段..."
  }
}
```

## 5. 部署与设置

### 5.1 服务器部署

1. **安装依赖**
```bash
pip install fastapi uvicorn websockets python-multipart
```

2. **启动服务**
```bash
python server.py --port 8081 --host 0.0.0.0
```

### 5.2 端口转发设置

用户需执行一次性设置：

```bash
# 连接跳板机
relay-cli

# 在跳板机上设置端口转发
ssh -N -L 8081:localhost:8081 bjhw-sys-rpm0221.bjhw.baidu.com
```

也可使用自动脚本：

```bash
./setup-tunnel.sh bjhw-sys-rpm0221.bjhw.baidu.com 8081
```

### 5.3 客户端配置

在Cursor插件中配置:

```json
{
  "serverUrl": "http://localhost:8081",
  "projectPath": "/home/user/project",
  "localPath": "/Users/localuser/project"
}
```

## 6. 安全性考虑

### 6.1 认证与授权

- 基于API密钥的简单认证
- 请求头中包含授权令牌
- 服务器验证令牌有效性

### 6.2 数据安全

- 所有通信通过SSH隧道加密
- 内网服务器仅监听localhost接口
- 文件传输采用校验和验证，确保完整性

## 7. 开发阶段规划

### 7.1 阶段一：服务器端实现（2周）

- HTTP服务器基本框架
- 文件系统操作API
- 命令执行功能
- WebSocket实时通知

### 7.2 阶段二：客户端开发（2周）

- Cursor插件基础结构
- 文件监控和同步
- 命令执行UI
- 通知和日志展示

### 7.3 阶段三：优化和测试（2周）

- 性能优化
- 错误处理
- 用户体验改进
- 全面测试

## 8. 使用流程

1. **初始设置**
   - 部署服务器端代码到内网服务器
   - 启动HTTP服务
   - 设置端口转发（一次性操作）

2. **日常开发**
   - 在Cursor中打开本地项目
   - 编辑文件自动同步到远程
   - 通过插件UI触发构建
   - 查看实时日志和结果

3. **高级功能**
   - 增量同步
   - 远程调试
   - 文件对比和合并
   - 自定义命令执行