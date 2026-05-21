import asyncio
from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.admin_connections: List[WebSocket] = []
        self.session_connections: Dict[str, List[WebSocket]] = defaultdict(list)

    async def connect_admin(self, websocket: WebSocket):
        await websocket.accept()
        self.admin_connections.append(websocket)

    async def connect_session(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.session_connections[session_id].append(websocket)

    def disconnect_admin(self, websocket: WebSocket):
        if websocket in self.admin_connections:
            self.admin_connections.remove(websocket)

    def disconnect_session(self, session_id: str, websocket: WebSocket):
        connections = self.session_connections.get(session_id, [])
        if websocket in connections:
            connections.remove(websocket)

    async def _send_many(self, connections: List[WebSocket], message: dict):
        stale = []
        for connection in list(connections):
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            if connection in connections:
                connections.remove(connection)

    async def broadcast_admin(self, message: dict):
        await self._send_many(self.admin_connections, message)

    async def broadcast_session(self, session_id: str, message: dict):
        await self._send_many(self.session_connections.get(session_id, []), message)

    async def broadcast(self, session_id: str, message: dict):
        await asyncio.gather(
            self.broadcast_admin(message),
            self.broadcast_session(session_id, message),
        )


manager = ConnectionManager()
latest_frames: Dict[str, bytes] = {}
latest_annotated_frames: Dict[str, bytes] = {}
latest_side_frames: Dict[str, bytes] = {}
latest_side_annotated_frames: Dict[str, bytes] = {}


def store_frame(session_id: str, frame_bytes: bytes, annotated_bytes: Optional[bytes] = None):
    latest_frames[session_id] = frame_bytes
    if annotated_bytes:
        latest_annotated_frames[session_id] = annotated_bytes


def store_side_frame(session_id: str, frame_bytes: bytes, annotated_bytes: Optional[bytes] = None):
    latest_side_frames[session_id] = frame_bytes
    if annotated_bytes:
        latest_side_annotated_frames[session_id] = annotated_bytes


def clear_side_frame(session_id: str):
    latest_side_frames.pop(session_id, None)
    latest_side_annotated_frames.pop(session_id, None)
