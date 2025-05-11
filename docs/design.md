# 百度远程开发MCP服务设计文档

## 1. 项目概述

### 1.1 背景

百度内部开发环境需要通过relay-cli跳板机连接，传统SSH连接方式无法直接与内部服务器建立持久可靠的连接。开发人员需要一种可靠的方式在本地IDE（如Cursor）中编辑代码，并在远程服务器上进行同步、编译、测试等操作。

### 1.2 目标

设计并实现一个基于HTTP协议的MCP（Message Communication Protocol）服务，实现本地开发环境与百度内网服务器之间的无缝连接，支持文件同步、远程编译、日志查看等功能，提高开发效率。

### 1.3 核心价值

- 消除开发环境障碍，实现真正的"本地开发，远程编译"
- 保留本地IDE的全部功能，同时获得远程服务器的强大算力
- 自动化流程，减少手动操作，提高开发效率
- 支持团队协作，可扩展性强

## 2. 系统架构

### 2.1 整体架构

系统由三个主要部分组成：

1. **本地客户端（Local Client）**
   - 集成到Cursor IDE
   - 监控本地文件变化
   - 发送文件同步请求
   - 展示编译状态和日志

2. **MCP服务器（MCP Server）**
   - 作为中间层，处理通信和任务调度
   - 维护会话和连接状态
   - 处理文件传输、编译请求等任务
   - 提供API接口供客户端调用

3. **远程执行器（Remote Executor）**
   - 部署在百度内网服务器上
   - 接收同步的文件
   - 执行编译和测试任务
   - 收集并返回日志和状态

### 2.2 架构图

```
┌─────────────────┐       ┌──────────────────┐      ┌────────────────────┐
│                 │       │                  │      │                    │
│  Local Client   │◄────►│   MCP Server     │◄────►│  Remote Executor   │
│   (Cursor IDE)  │       │ (Middleware)     │      │ (百度内网服务器)    │
│                 │       │                  │      │                    │
└─────────────────┘       └──────────────────┘      └────────────────────┘
      HTTP/WS                HTTP/WS + SSH                执行本地命令
```

## 3. 技术选型

### 3.1 客户端

- **语言/框架**: TypeScript + Electron（Cursor插件）
- **核心库**: 
  - `chokidar`: 文件监控
  - `axios`: HTTP请求
  - `socket.io-client`: WebSocket通信
  - `diff`: 差量更新计算

### 3.2 MCP服务器

- **语言/框架**: Python + FastAPI
- **核心库**:
  - `asyncio`: 异步IO处理
  - `websockets`: WebSocket支持
  - `pexpect`: 自动化交互式程序（relay-cli）
  - `SQLAlchemy`: 会话和状态管理
  - `redis`: 缓存和消息队列

### 3.3 远程执行器

- **语言/框架**: Python + Flask
- **核心库**:
  - `subprocess`: 执行系统命令
  - `watchdog`: 文件系统变化监控
  - `logging`: 日志收集

## 4. 核心功能与API设计

### 4.1 会话管理

#### 4.1.1 创建会话

```
POST /api/v1/sessions
Request:
{
  "project_id": "xblas_project",
  "server": "bjhw-sys-rpm0221.bjhw.baidu.com",
  "remote_path": "/home/xuyehua/projects/xblas",
  "build_command": "cd /home/xuyehua/projects/xblas && make"
}

Response:
{
  "session_id": "sess_1234567890",
  "status": "created",
  "ws_url": "ws://localhost:8000/ws/sess_1234567890"
}
```

#### 4.1.2 获取会话状态

```
GET /api/v1/sessions/{session_id}
Response:
{
  "session_id": "sess_1234567890",
  "status": "active",
  "last_sync": "2023-04-25T10:15:30Z",
  "last_build": "2023-04-25T10:20:45Z",
  "build_status": "success"
}
```

### 4.2 文件同步

#### 4.2.1 上传文件

```
PUT /api/v1/sessions/{session_id}/files
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
  "failed": 0
}
```

#### 4.2.2 获取远程文件

```
GET /api/v1/sessions/{session_id}/files?path=src/main.cpp
Response:
{
  "path": "src/main.cpp",
  "content": "base64_encoded_content",
  "last_modified": "2023-04-25T10:15:30Z",
  "checksum": "md5_hash"
}
```

### 4.3 构建管理

#### 4.3.1 触发构建

```
POST /api/v1/sessions/{session_id}/builds
Request:
{
  "command": "make all",  // 可选，覆盖默认命令
  "env": {                // 可选，环境变量
    "DEBUG": "1"
  }
}

Response:
{
  "build_id": "build_9876543210",
  "status": "started",
  "start_time": "2023-04-25T10:25:00Z"
}
```

#### 4.3.2 获取构建状态

```
GET /api/v1/sessions/{session_id}/builds/{build_id}
Response:
{
  "build_id": "build_9876543210",
  "status": "completed",
  "start_time": "2023-04-25T10:25:00Z",
  "end_time": "2023-04-25T10:26:30Z",
  "exit_code": 0,
  "log_url": "/api/v1/sessions/{session_id}/builds/{build_id}/logs"
}
```

#### 4.3.3 获取构建日志

```
GET /api/v1/sessions/{session_id}/builds/{build_id}/logs
Response:
{
  "logs": "编译日志内容...",
  "is_complete": true
}
```

### 4.4 WebSocket事件

#### 4.4.1 文件变更通知

```
{
  "type": "file_changed",
  "data": {
    "path": "src/main.cpp",
    "operation": "modified",
    "timestamp": "2023-04-25T10:30:15Z"
  }
}
```

#### 4.4.2 构建状态更新

```
{
  "type": "build_status",
  "data": {
    "build_id": "build_9876543210",
    "status": "running",
    "progress": 0.75,
    "current_step": "Linking object files"
  }
}
```

#### 4.4.3 日志流

```
{
  "type": "build_log",
  "data": {
    "build_id": "build_9876543210",
    "content": "新增日志内容片段...",
    "is_complete": false
  }
}
```

## 5. 数据流

### 5.1 文件同步流程

1. 本地客户端监测到文件变化
2. 计算变化的文件列表和差异
3. 通过API将变化上传到MCP服务器
4. MCP服务器接收文件并保存到缓存
5. MCP服务器通过SSH连接将文件传输到远程服务器
6. 远程执行器接收文件并保存到工作目录
7. 返回同步状态和确认信息

### 5.2 构建流程

1. 用户通过客户端触发构建
2. 客户端发送构建请求到MCP服务器
3. MCP服务器创建构建任务并排队
4. MCP服务器通过SSH连接执行远程构建命令
5. 远程执行器执行构建并实时收集日志
6. 日志和状态通过WebSocket实时返回给客户端
7. 构建完成后，结果和完整日志存储并返回

## 6. 安全性考虑

### 6.1 认证与授权

- 基于OAuth 2.0的用户认证
- 基于JWT的API访问授权
- 会话级别的访问控制

### 6.2 数据安全

- 所有通信采用HTTPS/WSS加密
- 敏感信息（如密码）不保存，仅在内存中临时使用
- 文件传输采用校验和验证，确保完整性

### 6.3 服务器安全

- 仅开放必要的网络端口
- 定期更新和安全补丁
- 日志审计和异常监控

## 7. 开发阶段规划

### 7.1 阶段一：核心功能实现（2周）

- MCP服务器基础框架搭建
- relay-cli自动化连接实现
- 基本的文件上传/下载功能
- 简单的构建触发和日志查看

**里程碑**: 能够通过HTTP API上传文件并触发远程构建

### 7.2 阶段二：功能完善（2周）

- WebSocket实时通知实现
- 差量文件同步算法
- 构建状态和日志实时流
- 多会话管理和并发控制

**里程碑**: 支持文件实时同步和构建状态实时反馈

### 7.3 阶段三：客户端集成（2周）

- Cursor插件开发
- 文件监控和自动同步
- 构建状态和日志展示UI
- 用户设置和配置管理

**里程碑**: 完整的Cursor插件可用，实现无缝开发体验

### 7.4 阶段四：优化和测试（2周）

- 性能优化和压力测试
- 异常处理和容错机制
- 文档和使用说明完善
- 内部用户测试反馈收集

**里程碑**: 系统稳定可靠，性能满足日常开发需求

## 8. 扩展性考虑

### 8.1 功能扩展

- 远程调试支持
- 代码审查集成
- 多人协作功能
- CI/CD流程集成

### 8.2 平台扩展

- 支持更多IDE（VSCode, IntelliJ等）
- 支持多种远程服务器环境
- 移动客户端支持

### 8.3 性能扩展

- 集群部署支持
- 负载均衡
- 分布式文件缓存

## 9. 设计理念

本设计遵循以下核心理念：

### 9.1 无缝体验

- 用户应该感觉不到远程与本地的区别
- 保留本地IDE的全部功能和性能
- 自动化处理复杂的连接和同步细节

### 9.2 可靠性优先

- 系统必须处理网络波动和断连情况
- 文件同步必须保证完整性和一致性
- 错误必须有清晰的反馈和恢复机制

### 9.3 模块化设计

- 系统各组件松耦合，便于独立开发和测试
- API接口标准化，支持不同客户端集成
- 功能可插拔，支持渐进式部署

### 9.4 开发者友好

- 配置简单，尽量减少手动设置
- 提供详细的状态反馈和错误诊断
- 支持个性化定制和工作流适配

## 10. 总结

本MCP服务设计旨在解决百度内网远程开发面临的连接和同步挑战，通过创建一个高效、可靠的中间层，使开发人员能够在本地IDE中无缝地进行远程开发。该设计充分考虑了实用性、安全性和扩展性，可以显著提高开发效率和体验。