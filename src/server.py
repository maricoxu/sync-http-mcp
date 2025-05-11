#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sync-HTTP-MCP Server

这是MCP服务器的主入口点，负责创建FastAPI应用、
设置路由和启动服务器。
"""

import logging
import os
from typing import Dict, List, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="Sync-HTTP-MCP",
    description="百度内网远程开发MCP服务",
    version="0.1.0",
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该限制为特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据模型
class Session(BaseModel):
    """会话数据模型"""
    project_id: str
    server: str
    remote_path: str
    build_command: Optional[str] = None


class SessionResponse(BaseModel):
    """会话响应模型"""
    session_id: str
    status: str
    ws_url: str


class FileSync(BaseModel):
    """文件同步数据模型"""
    files: List[Dict]


class FileSyncResponse(BaseModel):
    """文件同步响应模型"""
    status: str
    synchronized: int
    failed: int


class BuildRequest(BaseModel):
    """构建请求数据模型"""
    command: Optional[str] = None
    env: Optional[Dict[str, str]] = None


class BuildResponse(BaseModel):
    """构建响应模型"""
    build_id: str
    status: str
    start_time: str


# 应用状态
sessions = {}  # session_id -> session_data
builds = {}    # build_id -> build_data


# WebSocket连接管理
class ConnectionManager:
    """管理WebSocket连接"""
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """处理新的WebSocket连接"""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.info(f"WebSocket连接已建立, session_id={session_id}")

    def disconnect(self, websocket: WebSocket, session_id: str):
        """处理WebSocket断开连接"""
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        logger.info(f"WebSocket连接已断开, session_id={session_id}")

    async def broadcast(self, message: dict, session_id: str):
        """向指定会话的所有连接广播消息"""
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                await connection.send_json(message)
            logger.debug(f"消息已广播到session_id={session_id}: {message}")


manager = ConnectionManager()


# API路由
@app.get("/")
def read_root():
    """根路由，返回服务器信息"""
    return {"name": "Sync-HTTP-MCP", "version": "0.1.0"}


@app.post("/api/v1/sessions", response_model=SessionResponse)
def create_session(session: Session):
    """创建新会话"""
    # 生成会话ID
    import uuid
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    
    # 存储会话数据
    sessions[session_id] = {
        "data": session.dict(),
        "status": "created",
        "created_at": "2023-04-25T10:15:30Z",  # 这里应该使用实际时间
    }
    
    logger.info(f"创建会话: {session_id}")
    
    # 返回会话信息
    return {
        "session_id": session_id,
        "status": "created",
        "ws_url": f"ws://localhost:8000/ws/{session_id}"
    }


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str):
    """获取会话状态"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话未找到")
    
    return {
        "session_id": session_id,
        "status": sessions[session_id]["status"],
        "last_sync": sessions[session_id].get("last_sync", None),
        "last_build": sessions[session_id].get("last_build", None),
        "build_status": sessions[session_id].get("build_status", None)
    }


@app.put("/api/v1/sessions/{session_id}/files", response_model=FileSyncResponse)
def sync_files(session_id: str, file_sync: FileSync):
    """同步文件"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话未找到")
    
    # 实际应用中，这里需要实现文件同步到远程服务器的逻辑
    logger.info(f"同步文件到会话: {session_id}, 文件数: {len(file_sync.files)}")
    
    # 更新会话状态
    sessions[session_id]["last_sync"] = "2023-04-25T10:15:30Z"  # 这里应该使用实际时间
    
    return {
        "status": "success",
        "synchronized": len(file_sync.files),
        "failed": 0
    }


@app.post("/api/v1/sessions/{session_id}/builds", response_model=BuildResponse)
def create_build(session_id: str, build_request: BuildRequest):
    """触发构建"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话未找到")
    
    # 生成构建ID
    import uuid
    build_id = f"build_{uuid.uuid4().hex[:12]}"
    
    # 存储构建数据
    builds[build_id] = {
        "session_id": session_id,
        "command": build_request.command or sessions[session_id]["data"].get("build_command"),
        "env": build_request.env or {},
        "status": "started",
        "start_time": "2023-04-25T10:25:00Z",  # 这里应该使用实际时间
    }
    
    logger.info(f"创建构建: {build_id} for 会话: {session_id}")
    
    # 更新会话状态
    sessions[session_id]["last_build"] = "2023-04-25T10:25:00Z"  # 这里应该使用实际时间
    sessions[session_id]["build_status"] = "running"
    
    # 在实际应用中，这里需要启动一个后台任务来执行构建
    
    return {
        "build_id": build_id,
        "status": "started",
        "start_time": "2023-04-25T10:25:00Z"  # 这里应该使用实际时间
    }


@app.get("/api/v1/sessions/{session_id}/builds/{build_id}")
def get_build(session_id: str, build_id: str):
    """获取构建状态"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话未找到")
    
    if build_id not in builds or builds[build_id]["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="构建未找到")
    
    build = builds[build_id]
    
    return {
        "build_id": build_id,
        "status": build["status"],
        "start_time": build["start_time"],
        "end_time": build.get("end_time"),
        "exit_code": build.get("exit_code"),
        "log_url": f"/api/v1/sessions/{session_id}/builds/{build_id}/logs"
    }


@app.get("/api/v1/sessions/{session_id}/builds/{build_id}/logs")
def get_build_logs(session_id: str, build_id: str):
    """获取构建日志"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话未找到")
    
    if build_id not in builds or builds[build_id]["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="构建未找到")
    
    # 在实际应用中，这里需要从日志存储中读取构建日志
    
    return {
        "logs": "这是示例构建日志内容...\n构建成功完成。",
        "is_complete": True
    }


# WebSocket路由
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket连接处理"""
    if session_id not in sessions:
        await websocket.close(code=1008, reason="会话未找到")
        return
    
    await manager.connect(websocket, session_id)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            
            # 在实际应用中，这里需要处理客户端发送的消息
            logger.debug(f"收到WebSocket消息: {data}")
            
            # 示例：发送确认消息
            await websocket.send_json({"type": "ack", "data": {"message": "消息已收到"}})
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)


# 主入口点
if __name__ == "__main__":
    # 获取端口，默认为8000
    port = int(os.environ.get("PORT", 8000))
    
    # 启动服务器
    logger.info(f"启动Sync-HTTP-MCP服务器在端口 {port}...")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)