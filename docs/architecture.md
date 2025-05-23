# 系统架构详细说明

## 组件详解

### 1. 本地客户端 (Local Client)

本地客户端以Cursor IDE插件形式存在，主要负责：

#### 1.1 文件监控
- 使用`chokidar`库监控工作目录中的文件变化
- 支持忽略特定文件/目录（如.git, node_modules等）
- 维护文件状态缓存，支持差量计算

#### 1.2 通信管理
- 建立与MCP服务器的HTTP和WebSocket连接
- 实现重连和会话恢复机制
- 处理认证和授权

#### 1.3 用户界面
- 在IDE中显示同步状态和进度
- 提供编译和远程执行控制
- 展示编译日志和错误信息

### 2. MCP服务器 (MCP Server)

作为系统的核心中间层，MCP服务器负责：

#### 2.1 会话管理
- 管理用户会话和项目配置
- 处理身份验证和权限控制
- 维护连接状态和活跃度监控

#### 2.2 文件同步
- 接收本地文件更改
- 实现文件差量传输算法
- 通过SSH/SCP将文件同步到远程服务器

#### 2.3 命令执行
- 通过`pexpect`自动化relay-cli连接过程
- 执行远程编译和测试命令
- 收集命令输出和退出状态

#### 2.4 事件通知
- 通过WebSocket推送实时事件
- 支持文件变更、编译状态和日志流通知
- 实现事件订阅和过滤机制

### 3. 远程执行器 (Remote Executor)

部署在百度内网服务器上的组件，负责：

#### 3.1 文件操作
- 接收和保存同步的文件
- 维护文件版本和状态
- 处理文件权限和所有权

#### 3.2 命令执行
- 在工作目录中执行编译命令
- 管理执行环境和变量
- 捕获标准输出和错误输出

#### 3.3 状态报告
- 收集命令执行状态
- 格式化和传输日志
- 生成执行报告和统计信息

## 数据流详解

### 1. 文件同步数据流

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  文件修改   │─────►│计算文件差异 │─────►│ HTTP PUT请求 │─────►│MCP服务接收  │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
                                                                      │
                                                                      ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│确认完成同步 │◄─────│文件写入确认 │◄─────│远程文件写入 │◄─────│SSH文件传输  │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
```

### 2. 构建执行数据流

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ 触发构建请求│─────►│创建构建任务 │─────►│ HTTP POST请求│─────►│MCP服务接收  │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
                                                                      │
                                                                      ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│WebSocket通知│◄─────│日志实时流式 │◄─────│命令执行输出 │◄─────│SSH执行命令  │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
       │                                                               │
       │                                                               ▼
       │                ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
       └───────────────►│更新构建状态 │◄─────│状态码检查   │◄─────│命令执行完成 │
                        └─────────────┘      └─────────────┘      └─────────────┘
```

## 接口设计详解

### API版本控制

所有API都遵循`/api/v{version}/...`格式，当前版本为v1。这允许未来API变更而不破坏现有客户端。

### 错误处理

所有API使用标准HTTP状态码，同时返回详细错误信息：

```json
{
  "error": {
    "code": "session_not_found",
    "message": "The specified session was not found or has expired",
    "details": {
      "session_id": "sess_1234567890"
    }
  }
}
```

### 分页

支持集合资源的分页：

```
GET /api/v1/sessions/{session_id}/builds?page=2&per_page=25
```

响应中包含分页元数据：

```json
{
  "data": [...],
  "pagination": {
    "page": 2,
    "per_page": 25,
    "total": 125,
    "pages": 5
  }
}
```

### 缓存控制

使用标准HTTP缓存控制头，确保客户端得到最新数据：

```
Cache-Control: no-cache, no-store, must-revalidate
Pragma: no-cache
Expires: 0
```

## 安全设计详解

### 传输安全

- 所有HTTP通信使用TLS 1.3加密
- WebSocket连接使用WSS（WebSocket Secure）
- 证书由可信CA签发或使用自签名证书（开发环境）

### 身份验证流程

1. 客户端请求登录：
   ```
   POST /api/v1/auth/login
   {
     "username": "user@baidu.com",
     "password": "password"
   }
   ```

2. 服务器验证凭据并返回JWT：
   ```
   {
     "access_token": "eyJhbGciOiJIUzI1NiIsInR...",
     "refresh_token": "eyJhbGciOiJIUzI1NiIsInR...",
     "expires_in": 3600
   }
   ```

3. 客户端在后续请求中使用Bearer认证：
   ```
   Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR...
   ```

### 授权模型

基于RBAC（基于角色的访问控制）：

- **User**: 基本用户，可以访问自己的项目
- **Admin**: 管理员，可以管理用户和系统设置
- **ProjectOwner**: 项目所有者，可以管理项目设置和用户

## 部署架构

### 开发环境

```
┌─────────────────────────┐
│      开发机(本地)        │
│                         │
│  ┌─────────┐ ┌────────┐ │
│  │ Cursor  │ │MCP服务器│ │
│  └─────────┘ └────────┘ │
└─────────────────────────┘
           │
           ▼
┌─────────────────────────┐
│       百度内网服务器      │
│                         │
│      ┌──────────────┐   │
│      │  远程执行器   │   │
│      └──────────────┘   │
└─────────────────────────┘
```

### 生产环境

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  开发者1    │     │  开发者2    │     │  开发者3    │
│ (Cursor)    │     │ (Cursor)    │     │ (Cursor)    │
└─────────────┘     └─────────────┘     └─────────────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │
                          ▼
               ┌─────────────────────┐
               │   负载均衡器        │
               └─────────────────────┘
                 │             │
        ┌────────┘             └────────┐
        │                               │
┌───────────────┐               ┌───────────────┐
│ MCP服务实例1  │               │ MCP服务实例2  │
└───────────────┘               └───────────────┘
        │                               │
        └────────┐             ┌────────┘
                 │             │
           ┌─────────────────────┐
           │   数据库/缓存        │
           └─────────────────────┘
                     │
                     ▼
           ┌─────────────────────┐
           │   百度内网服务器     │
           └─────────────────────┘
```

## 扩展性设计

### 插件系统

MCP服务器支持插件系统，允许第三方开发者扩展功能：

```python
from sync_http_mcp.plugins import Plugin

class CustomPlugin(Plugin):
    def initialize(self):
        self.register_hook('pre_build', self.on_pre_build)
    
    async def on_pre_build(self, session, build_request):
        # 自定义前置构建逻辑
        pass
```

### 事件系统

基于发布-订阅模式的事件系统：

```python
# 发布事件
await event_bus.publish('file.changed', {
    'session_id': session_id,
    'file_path': 'src/main.cpp',
    'operation': 'modified'
})

# 订阅事件
@event_bus.subscribe('file.changed')
async def on_file_changed(data):
    # 处理文件变更事件
    pass
```

### API扩展

支持API版本控制和自定义端点：

```python
@app.register_extension('v1', 'sessions/{session_id}/custom')
async def custom_endpoint(request, session_id):
    # 自定义API逻辑
    return {'result': 'success'}
```