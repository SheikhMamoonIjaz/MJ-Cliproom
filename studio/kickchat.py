"""Kick chat messages, counted the same way as Twitch chat.

Kick sends chat over a Pusher websocket. This module only decides whether a
frame is a viewer message. The live recorder uses that to mark a busy second.
"""
import json


def is_chat_message(payload) -> bool:
    """True when this Pusher frame is one viewer chat message."""
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return False
    if not isinstance(payload, dict):
        return False
    event = str(payload.get("event") or "")
    if "ChatMessage" not in event:
        return False
    data = payload.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return False
    if isinstance(data, dict):
        return bool(str(data.get("content") or data.get("message") or "").strip())
    return False


def chatroom_id(channel: dict):
    """The chatroom id from a Kick channel JSON payload, or None."""
    room = channel.get("chatroom") if isinstance(channel, dict) else None
    if isinstance(room, dict) and room.get("id"):
        return str(room["id"])
    if channel.get("chatroom_id"):
        return str(channel["chatroom_id"])
    return None
