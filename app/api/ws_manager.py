from fastapi import WebSocket
from typing import Dict
import json


class ConnectionManager:
    def __init__(self):
        self.customer: Dict[int, WebSocket] = {}   # conv_id -> ws
        self.admin: Dict[int, WebSocket] = {}       # user_id -> ws

    async def connect_customer(self, conv_id: int, ws: WebSocket):
        await ws.accept()
        self.customer[conv_id] = ws

    async def connect_admin(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.admin[user_id] = ws

    def disconnect_customer(self, conv_id: int):
        self.customer.pop(conv_id, None)

    def disconnect_admin(self, user_id: int):
        self.admin.pop(user_id, None)

    async def send_to_customer(self, conv_id: int, data: dict):
        ws = self.customer.get(conv_id)
        if ws:
            await ws.send_text(json.dumps(data))

    async def send_to_admin(self, user_id: int, data: dict):
        ws = self.admin.get(user_id)
        if ws:
            await ws.send_text(json.dumps(data))

    async def broadcast_to_all_admins(self, data: dict):
        for ws in self.admin.values():
            await ws.send_text(json.dumps(data))


manager = ConnectionManager()
