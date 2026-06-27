from fastapi import WebSocket
from typing import Dict
import json


class ConnectionManager:
    def __init__(self):
        self.customer_by_channel: Dict[int, WebSocket] = {}   # keyed by URL int (channel_id)
        self.customer_by_db_id: Dict[int, WebSocket] = {}     # keyed by DB conv.id
        self.admin: Dict[int, WebSocket] = {}                  # keyed by user_id

    async def connect_customer(self, channel_id: int, db_id: int, ws: WebSocket):
        await ws.accept()
        self.customer_by_channel[channel_id] = ws
        self.customer_by_db_id[db_id] = ws

    def disconnect_customer(self, channel_id: int, db_id: int):
        self.customer_by_channel.pop(channel_id, None)
        self.customer_by_db_id.pop(db_id, None)

    async def send_to_customer_by_channel(self, channel_id: int, data: dict):
        ws = self.customer_by_channel.get(channel_id)
        if ws:
            await ws.send_json(data)

    async def send_to_customer_by_db_id(self, db_id: int, data: dict):
        ws = self.customer_by_db_id.get(db_id)
        if ws:
            await ws.send_json(data)

    async def connect_admin(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.admin[user_id] = ws

    def disconnect_admin(self, user_id: int):
        self.admin.pop(user_id, None)

    async def send_to_admin(self, user_id: int, data: dict):
        ws = self.admin.get(user_id)
        if ws:
            await ws.send_json(data)

    async def broadcast_to_all_admins(self, data: dict):
        for ws in list(self.admin.values()):
            await ws.send_json(data)


manager = ConnectionManager()
