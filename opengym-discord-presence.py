#!/usr/bin/env python3
"""openGym -> Discord Rich Presence por IPC local (necesita el cliente Discord en este host).

Requiere: OG_SECRET, OG_UID, DISCORD_CLIENT_ID. Opcional: OG_URL, OG_SV, DISCORD_ASSET, POLL.
Uso: ./opengym-discord-presence.py [--once]   (--once imprime el payload y sale, sin Discord)
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request

from pypresence import Presence

OG = os.environ.get("OG_URL", "http://100.71.223.9:31180").rstrip("/")
# URL que Discord debe poder alcanzar para la imagen: su proxy la baja desde SUS servidores,
# así que una IP LAN/Tailscale no sirve. Tiene que ser el host público (funnel, dominio, etc.).
PUBLIC = os.environ.get("OG_PUBLIC", "").rstrip("/") or OG
UID = os.environ.get("OG_UID", "")
SECRET = os.environ.get("OG_SECRET", "")
SV = int(os.environ.get("OG_SV", "0"))          # user.sv en data/db.json
CLIENT = os.environ.get("DISCORD_CLIENT_ID", "")
ASSET = os.environ.get("DISCORD_ASSET", "opengym")
POLL = int(os.environ.get("POLL", "20"))
_groups = {}                                     # nombre de rutina -> ids por grupo


def cookie():
    """Sesión firmada igual que el server (sign(): HMAC-SHA256 base64url de uid:exp:sv:c)."""
    exp = int(time.time() * 1000) + 86400000
    payload = f"{UID}:{exp}:{SV}:c"
    mac = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return payload + "." + mac


def live():
    req = urllib.request.Request(
        f"{OG}/api/admin/users", headers={"Cookie": "__Host-gymsid=" + cookie()}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        users = json.load(r)["users"]
    user = next((u for u in users if u.get("id") == UID), None)
    return user and user.get("live")


def routine_groups(name):
    """Ids de ejercicio, uno por grupo, para el nombre de rutina que manda el heartbeat.

    El heartbeat trae el nombre de la rutina y `exIdx` = índice de GRUPO (un superset es un
    grupo), así que hay que reproducir el agrupado del front: vecinos con el mismo `sg`.
    Se resuelve una vez por rutina: cambia solo al arrancar otro entrenamiento.
    """
    if not name:
        return []
    if name in _groups:
        return _groups[name]
    req = urllib.request.Request(
        f"{OG}/api/data", headers={"Cookie": "__Host-gymsid=" + cookie()}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        routines = json.load(r)["state"].get("routines") or []
    routine = next((x for x in routines if x.get("name") == name), None)
    if not routine:
        return []
    ids = group_ids(routine.get("ex") or [])
    _groups[name] = ids
    return ids


def group_ids(ex):
    """Primer id de cada grupo: vecinos adyacentes con el mismo `sg` son un superset."""
    out = []
    for e in ex:
        sg = e.get("sg")
        if out and sg and sg == out[-1][-1].get("sg"):
            out[-1].append(e)
        else:
            out.append([e])
    return [g[0]["id"] for g in out if g and g[0].get("id")]


def payload(p):
    ex_total = max(0, p.get("exTotal") or 0)
    ex_idx = max(0, p.get("exIdx") or 0)
    sets_total = max(0, p.get("setsTotal") or 0)
    sets_done = max(0, p.get("setsDone") or 0)
    # exIdx cuenta GRUPOS (un superset es un grupo), no ejercicios sueltos.
    state = f"{sets_done}/{sets_total} sets"
    if ex_total > 1:
        state += f" · {ex_idx}/{ex_total}"

    out = {
        "details": (p.get("name") or "Training")[:128],
        "state": state[:128],
        "large_image": ASSET,
        "large_text": "openGym",
    }
    # Imagen: el still del ejercicio que está haciendo, servido por la app. Discord la baja
    # desde su proxy, así que PUBLIC tiene que ser alcanzable desde internet (no LAN/Tailscale).
    ids = routine_groups(p.get("name"))
    if 0 < ex_idx <= len(ids):
        out["large_image"] = f"{PUBLIC}/exercise-media/still/{ids[ex_idx - 1]}.webp"
    started = int((p.get("startedAt") or 0) / 1000)
    # Una sesión dejada abierta días mostraría "hace 3 días": sin contador pasado un margen.
    if started and 0 < time.time() - started < 4 * 3600:
        out["start"] = started
    return out


def main():
    once = "--once" in sys.argv
    rpc = None
    while True:
        try:
            p = live()
            pl = payload(p) if p else None
            if once:
                print(json.dumps(pl, ensure_ascii=False, indent=2) if pl else "nada en curso")
                return
            if rpc is None:
                rpc = Presence(CLIENT)
                rpc.connect()
                print("conectado a Discord", flush=True)
            if pl:
                rpc.update(**pl)
            else:
                rpc.clear()
        except Exception as e:  # Discord cerrado, red, 401 del server: reintentar
            print(f"{time.strftime('%H:%M:%S')} {type(e).__name__}: {e}", flush=True)
            try:
                rpc and rpc.close()
            except Exception:
                pass
            rpc = None
            if once:
                raise
            time.sleep(5)
            continue
        time.sleep(POLL)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Un superset (mismo sg seguido) cuenta como UN grupo; un sg suelto o repetido no une.
        assert group_ids([{"id": "a"}, {"id": "b", "sg": "x"}, {"id": "c", "sg": "x"},
                          {"id": "d"}, {"id": "e", "sg": "y"}]) == ["a", "b", "d", "e"]
        pl = payload({"name": "", "exIdx": 0, "exTotal": 0, "setsDone": 3, "setsTotal": 9})
        assert pl["state"] == "3/9 sets" and pl["large_image"] == ASSET and "start" not in pl
        print("ok")
        raise SystemExit
    main()
