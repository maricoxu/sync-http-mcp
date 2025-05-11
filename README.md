# Sync-HTTP-MCP

百度内网远程开发服务 - 实现本地IDE与百度内网服务器无缝协作

## 项目简介

Sync-HTTP-MCP是一个专为百度内网开发环境设计的远程开发解决方案，通过HTTP/WebSocket协议实现本地IDE（如Cursor）与远程服务器的实时同步、编译和日志获取。

本项目使用直接部署方式，将HTTP服务器部署在百度内网服务器上，简化架构并提高可靠性。

## 核心功能

- **文件实时同步**：本地文件修改自动同步到远程服务器
- **远程编译**：一键触发远程服务器编译，无需手动登录
- **日志实时反馈**：编译和执行日志实时返回本地
- **状态监控**：远程任务执行状态实时可见
- **差量传输**：仅传输变更内容，高效节省带宽

## 技术架构

- **客户端**：极简设计的Python客户端，仅依赖requests和websocket-client库
- **服务器端**：部署在百度内网服务器上的HTTP服务，处理文件操作和命令执行

## 快速开始

### 1. 安装依赖

```bash
# 安装基本依赖
pip install requests>=2.25.0 websocket-client>=1.0.0

# 可选：使用国内镜像加速安装
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests>=2.25.0 websocket-client>=1.0.0
```

### 2. 服务器设置

将服务端代码部署到百度内网服务器:

```bash
# 登录到内网服务器
relay-cli
ssh bjhw-sys-rpm0221.bjhw.baidu.com

# 或使用webrelay登录

# 创建并启动Docker容器
docker run \
    --privileged \
    --name=xuyehua_torch \
    --ulimit core=-1 \
    --security-opt seccomp=unconfined \
    -dti \
    --net=host --uts=host --ipc=host \
    --security-opt=seccomp=unconfined \
    -v /home:/home \
    -v /data1:/data1 \
    -v /data2:/data2 \
    -v /data3:/data3 \
    -v /data4:/data4 \
    --shm-size=256g \
    --restart=always \
    iregistry.baidu-int.com/xmlir/xmlir_ubuntu_2004_x86_64:v0.32

# 进入容器环境
docker exec -it xuyehua_torch bash

# 在Docker容器中设置服务
mkdir -p /home/sync-http-mcp
cd /home/sync-http-mcp

# 下载服务器启动脚本
bcecmd bos cp bos:/klx-pytorch-work-bd-bj/xuyehua/scripts/start_server.sh .

# 添加执行权限
chmod +x start_server.sh

# 启动服务
./start_server.sh
```

详细的服务器设置指南请参考[使用指南](./docs/USAGE.md)。

### 3. 使用客户端

客户端现在支持多种默认值，命令更加简洁：

```bash
# 列出远程目录内容 (默认: /home)
python src/client.py list

# 同步本地目录到远程 (默认: 当前目录 -> /home)
python src/client.py sync

# 上传本地文件 (默认远程路径: /home/文件名)
python src/client.py put local_file.txt

# 执行远程命令 (默认目录: /home)
python src/client.py --command "ls -la"
```

### 4. 多设备协作

您可以从不同设备（家庭和办公室）访问相同的远程服务器：

```bash
# 在办公室电脑上
python src/client.py --server http://10.20.30.40:8081 sync

# 在家里电脑上
python src/client.py --server http://10.20.30.40:8081 sync
```

## 系统架构

```
┌─────────────────┐                    ┌────────────────────┐
│                 │                    │                    │
│  Local Client   │◄────HTTP/WS──────►│  Remote HTTP Server │
│   (Python)      │                    │  (百度内网服务器)     │
│                 │                    │                    │
└─────────────────┘                    └────────────────────┘
```

## 详细文档

- [安装指南](./INSTALL.md) - 详细的安装和配置说明
- [使用指南](./docs/USAGE.md) - 详细的客户端使用方法
- [API参考](./docs/API.md) - 服务器API接口说明

## 简化设计

本项目采用简化设计原则：

1. **极简依赖**：客户端仅依赖requests和websocket-client两个库
2. **同步操作**：提供同步API调用方式，简化编程模型
3. **直接通信**：使用HTTP/WebSocket直接通信，无需复杂中间件
4. **直接网络访问**：服务器监听公共IP，无需端口转发
5. **智能默认值**：客户端命令支持合理默认值，减少输入

## 推荐使用流程

1. **初始设置**
   - 部署服务器代码到内网服务器
   - 安装客户端依赖
   - 记录服务器IP地址

2. **日常开发**
   - 编写代码，使用客户端同步到远程
   - 触发远程编译和测试
   - 查看实时日志输出

## 路线图

- [x] 服务器端基础实现
- [x] 简化客户端实现
- [x] 支持多设备协作
- [ ] 增量同步算法优化
- [ ] 远程调试支持
- [ ] 自动化配置工具

## 贡献

欢迎贡献代码、报告问题或提出改进建议。

## 许可证

[MIT License](./LICENSE)