"""Persistent user storage backed by the Supabase REST API.

The service-role key is used only by the private Telegram bot process.
Never ship it to a client application or expose it in logs.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _request(method: str, path: str, *, params=None, payload=None, prefer=None):
    if not is_configured():
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured."
        )
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Supabase request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Supabase connection failed: {exc.reason}") from exc


def _upsert(table: str, row: dict):
    return _request(
        "POST", table, params={"on_conflict": "user_id"}, payload=row,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def save_user(uid: int, name: str, username: str):
    _upsert("bot_users", {
        "user_id": uid, "name": name or "", "username": username or "",
        "last_seen": datetime.now(timezone.utc).isoformat()
    })


def get_city(uid: int):
    rows = _request(
        "GET", "bot_users",
        params={"select": "city", "user_id": f"eq.{uid}", "limit": "1"},
    ) or []
    return rows[0].get("city") if rows else None


def get_qari(uid: int):
    rows = _request("GET", "bot_users", params={"select": "qari_id", "user_id": f"eq.{uid}", "limit": "1"}) or []
    return rows[0].get("qari_id") if rows else None


def set_qari(uid: int, qari_id: str):
    _upsert("bot_users", {"user_id": uid, "qari_id": str(qari_id)})


def is_setup_completed(uid: int) -> bool:
    rows = _request("GET", "bot_users", params={"select": "setup_completed", "user_id": f"eq.{uid}", "limit": "1"}) or []
    return bool(rows[0].get("setup_completed", False)) if rows else False


def set_setup_completed(uid: int, completed: bool = True):
    _upsert("bot_users", {"user_id": uid, "setup_completed": bool(completed)})


def save_feedback(uid: int, category: str, message: str):
    _request("POST", "bot_feedback", payload={
        "user_id": uid, "category": category or "general", "message": message
    }, prefer="return=minimal")


def touch_runtime_heartbeat(status: str = "running"):
    _request("POST", "bot_runtime", params={"on_conflict": "id"}, payload={
        "id": 1, "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "status": status, "run_id": os.getenv("GITHUB_RUN_ID", ""),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "")
    }, prefer="resolution=merge-duplicates,return=minimal")


def get_prayer_notifications(uid: int) -> bool:
    rows = _request(
        "GET", "bot_users",
        params={"select": "prayer_notifications", "user_id": f"eq.{uid}", "limit": "1"},
    ) or []
    return bool(rows[0].get("prayer_notifications", False)) if rows else False


def set_prayer_notifications(uid: int, enabled: bool):
    _upsert("bot_users", {"user_id": uid, "prayer_notifications": bool(enabled)})


def list_prayer_notification_users():
    return _request(
        "GET", "bot_users",
        params={"select": "user_id,city", "prayer_notifications": "eq.true", "limit": "10000"},
    ) or []


def claim_prayer_notification(uid: int, prayer_date: str, prayer_key: str) -> bool:
    rows = _request(
        "POST", "bot_prayer_notifications_sent",
        params={"on_conflict": "user_id,prayer_date,prayer_key"},
        payload={"user_id": uid, "prayer_date": prayer_date, "prayer_key": prayer_key},
        prefer="resolution=ignore-duplicates,return=representation",
    )
    return bool(rows)


def set_city(uid: int, city: str):
    _upsert("bot_users", {"user_id": uid, "city": city})


def get_tasbih_zikr(uid: int) -> int:
    rows = _request("GET", "bot_users", params={"select": "tasbih_zikr", "user_id": f"eq.{uid}", "limit": "1"}) or []
    return int(rows[0].get("tasbih_zikr", -1)) if rows else -1


def set_tasbih_zikr(uid: int, zikr_index: int):
    _upsert("bot_users", {"user_id": uid, "tasbih_zikr": int(zikr_index)})


def get_menu_order(uid: int):
    rows = _request("GET", "bot_users", params={"select": "menu_order", "user_id": f"eq.{uid}", "limit": "1"}) or []
    value = rows[0].get("menu_order") if rows else None
    return value if isinstance(value, list) else []


def set_menu_order(uid: int, order: list[str]):
    _upsert("bot_users", {"user_id": uid, "menu_order": order})


def init_user_features():
    # Tables are provisioned once in Supabase; never create them at runtime.
    return None


def save_last_read(uid: int, sid: int, offset: int):
    _request(
        "POST", "bot_last_read", params={"on_conflict": "user_id"},
        payload={"user_id": uid, "surah_id": sid, "ayah_offset": offset},
        prefer="resolution=merge-duplicates,return=minimal",
    )


def add_favorite(uid: int, sid: int, ayah: int, title: str) -> bool:
    rows = _request(
        "POST", "bot_favorites",
        params={"on_conflict": "user_id,surah_id,ayah"},
        payload={"user_id": uid, "surah_id": sid, "ayah": ayah, "title": title},
        prefer="resolution=ignore-duplicates,return=representation",
    )
    return bool(rows)


def remove_favorite(uid: int, favorite_id: int):
    _request(
        "DELETE", "bot_favorites",
        params={"id": f"eq.{favorite_id}", "user_id": f"eq.{uid}"},
        prefer="return=minimal",
    )


def list_favorites(uid: int):
    rows = _request(
        "GET", "bot_favorites",
        params={
            "select": "id,surah_id,ayah,title", "user_id": f"eq.{uid}",
            "order": "id.desc", "limit": "30",
        },
    ) or []
    return [(r["id"], r["surah_id"], r["ayah"], r["title"]) for r in rows]


def get_last_read(uid: int):
    rows = _request(
        "GET", "bot_last_read",
        params={"select": "surah_id,ayah_offset", "user_id": f"eq.{uid}", "limit": "1"},
    ) or []
    return (rows[0]["surah_id"], rows[0]["ayah_offset"]) if rows else None


def get_tasbih(uid: int):
    rows = _request(
        "GET", "bot_users",
        params={"select": "tasbih", "user_id": f"eq.{uid}", "limit": "1"},
    ) or []
    return (rows[0]["tasbih"],) if rows else None


def change_tasbih(uid: int, change: int) -> int:
    result = _request(
        "POST", "rpc/bot_change_tasbih",
        payload={"p_user_id": uid, "p_change": change},
    )
    return int(result or 0)


def reset_tasbih(uid: int):
    _request(
        "PATCH", "bot_users", params={"user_id": f"eq.{uid}"},
        payload={"tasbih": 0}, prefer="return=minimal",
    )


def get_user_count() -> int:
    result = _request("POST", "rpc/bot_user_count", payload={})
    return int(result or 0)


def list_users(limit: int = 10, offset: int = 0):
    rows = _request(
        "GET", "bot_users",
        params={
            "select": "user_id,name,username,created_at,last_seen",
            "order": "last_seen.desc", "limit": str(limit), "offset": str(offset),
        },
    ) or []
    return rows


def get_admin_stats():
    users = get_user_count()
    # PostgREST exact counts are returned in Content-Range; use lightweight row counts as a fallback.
    return {"users": users, "favorites": len(_request("GET", "bot_favorites", params={"select": "id", "limit": "10000"}) or []),
            "last_reads": len(_request("GET", "bot_last_read", params={"select": "user_id", "limit": "10000"}) or []),
            "banned": len(_request("GET", "bot_bans", params={"select": "user_id", "limit": "10000"}) or [])}


def is_banned(uid: int) -> bool:
    rows = _request("GET", "bot_bans", params={"select": "user_id", "user_id": f"eq.{uid}", "limit": "1"}) or []
    return bool(rows)


def ban_user(uid: int, reason: str = ""):
    _request("POST", "bot_bans", payload={"user_id": uid, "reason": reason or ""},
             prefer="resolution=merge-duplicates,return=minimal")


def unban_user(uid: int):
    _request("DELETE", "bot_bans", params={"user_id": f"eq.{uid}"}, prefer="return=minimal")
