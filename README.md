# opengym-discord-presence

Show your live workout from [openGym](https://gitlab.com/DuarteSantos28/opengym) as a
Discord Rich Presence card: the routine you are on, how many sets you have done, the
position in the session, a running timer, and the exercise's own picture.

```
Playing openGym
  Tren superior
  20/25 sets · 4/4
  ──────────────────────── 41:04
```

One Python file, no dependencies beyond `pypresence`.

## How it works (and why it runs where it runs)

Discord only accepts presence from a Discord client logged into **your** account on the
**same machine**, through a local socket (`$XDG_RUNTIME_DIR/discord-ipc-0`). A phone or a
server cannot set a human's activity, and a user token against the gateway is a self-bot
(bannable). So this script has to run next to a Discord client — your desktop, or a
headless client on a server — and read the workout over openGym's HTTP API.

openGym has this to read because the web app heartbeats while a workout is open:
`POST /api/activity` every 20 s with the routine name, the sets done and the position in
the session. The API keeps it **in memory only** (70 s TTL, plus 45 s of grace when the app
goes to the background), which is exactly the granularity a presence card wants. The
in-progress workout is never written to disk, so this is the only place it exists.

## Requirements

- Python 3.8+ and `pip install pypresence`
- A Discord client running and logged in on the same machine
- openGym reachable over HTTP from that machine, and an **admin** account (see below)

## 1. Connect to openGym

The only endpoint that exposes live workouts is `GET /api/admin/users` — the admin
dashboard's "training now" list. There is no public or self endpoint, so the script has to
authenticate as an admin. It does that with the instance's own signing key, `data/secret`,
the same way the API mints its session cookie (HMAC-SHA256 over `uid:expiry:version:c`).

Three values, all inside your openGym data directory (the volume mounted at `/data` in the
API container — `./data` if you followed the bundled compose file):

| Value | How to get it |
|---|---|
| `uid` | `ls data/state-*.json` (the id is in the filename), or `jq -r '.users[].id' data/db.json` |
| `secret` | `cat data/secret` |
| `sv` | `jq -r '.users[] \| select(.id=="<uid>") \| .sv // 0' data/db.json` |

Inside Docker:

```bash
docker compose exec api cat /data/secret
docker compose exec api ls /data
```

Treat `data/secret` like a root password: whoever holds it can act as any account on the
instance. Keep the config file at mode `600`. Rotating it (`rm data/secret` and restart the
API) signs everyone out and invalidates the script until you paste the new value in — the
same thing happens if you ever press *sign out everywhere*, which bumps the account's `sv`.

If you would rather not hand over the key, the alternative is patching the API to expose
`GET /api/activity` for the signed-in user — a change you would have to reapply on every
upgrade.

## 2. Connect to Discord

1. <https://discord.com/developers/applications> → **New Application** → name it `openGym`
   (this text is what appears in the card: "Playing openGym").
2. **General Information** → copy the **Application ID** → that is `client_id`.
3. **Rich Presence → Art Assets** → upload a logo with the key `opengym`. That key is
   `asset`, and it is only the fallback image: whenever the script can resolve the exercise,
   the card shows the exercise's own picture instead.

No bot, no token, no invite: this is a plain rich presence client.

## 3. Configure

Copy `config.example.json` next to the script as `config.json`, or put it anywhere and point
at it with `--config /path/config.json` (or `OG_CONFIG`):

```bash
install -m 600 config.example.json config.json
$EDITOR config.json
```

```json
{
  "url": "http://127.0.0.1:31180",
  "public_url": "",
  "uid": "YOUR_OPEN_GYM_UID",
  "secret": "PASTE_DATA_SECRET",
  "sv": 0,
  "client_id": "YOUR_DISCORD_APPLICATION_ID",
  "asset": "opengym",
  "poll": 20
}
```

| Key | Required | Default | Meaning |
|---|---|---|---|
| `url` | yes | `http://127.0.0.1:31180` | Where this host reaches openGym (the web container; it proxies `/api`) |
| `public_url` | no | `url` | Same app at a URL **reachable from the internet** — Discord downloads the exercise picture from its own servers. Leave empty on a private instance and the card uses `asset` |
| `uid` | yes | — | Your openGym user id |
| `sv` | no | `0` | Your user's `sv` in `db.json` |
| `secret` | yes | — | Contents of `data/secret` |
| `client_id` | yes | — | Discord Application ID |
| `asset` | no | `opengym` | Asset key for the fallback image |
| `poll` | no | `20` | Seconds between polls (the client beats every 20 s, a row expires at 70 s) |

Every key can also come from an environment variable (`OG_URL`, `OG_PUBLIC`, `OG_UID`,
`OG_SECRET`, `OG_SV`, `DISCORD_CLIENT_ID`, `DISCORD_ASSET`, `POLL`) — handy in containers.
Values in `config.json` win over the environment.

The picture needs `public_url`: Discord's image proxy fetches the URL from **its** servers,
so a LAN, VPN or Tailscale address renders as an empty box. Any public reverse proxy,
tunnel or hostname works.

## 4. Test

```bash
pip install pypresence
./opengym-discord-presence.py --selftest    # parsing/grouping only, no network
./opengym-discord-presence.py --once        # what it would send, no Discord
```

`--once` exercises the login, the JSON and the card text in one shot: it prints the payload
or `nada en curso`. If that works but nothing shows on your profile, the problem is the
Discord side, not openGym.

Start a workout in the app and run it without flags — the card appears within one poll and
clears by itself within ~20 s of finishing.

## 5. Deploy as a service

The script must run as the user that owns the Discord IPC socket:

```bash
sudo install -m 755 opengym-discord-presence.py /usr/local/bin/
sudo install -m 600 config.example.json /etc/opengym-presence.json   # then edit it
sudo install -m 644 opengym-discord-presence.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opengym-discord-presence
journalctl -u opengym-discord-presence -f
```

Adjust the unit before enabling it: `ExecStart` (script path and `--config`), `User`, and
`XDG_RUNTIME_DIR` (the runtime dir of the user running Discord — `/run/user/1000` for the
first user, `/run/user/0` for root). No desktop session on that machine? See
[docs/headless-discord.md](docs/headless-discord.md) for running the Discord client on a
virtual display (~500 MB RAM).

Docker instead: the container needs both the Discord client and this script — it is one
process talking to a Unix socket, so nothing is gained by splitting them.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `falta configurar: ...` | `uid`, `secret` or `client_id` is empty — check which config file it read (`--config`) |
| `HTTPError 401` | `secret`, `uid` or `sv` is wrong — the server signs sessions with its own key |
| `HTTPError 403` | that user isn't an admin |
| `ConnectionRefusedError` | Discord isn't running, or `XDG_RUNTIME_DIR` points to another user's runtime dir |
| `User logged out` (error 1000) | Discord lost the session — check the client's screen and log in again |
| Card never appears but `--once` prints a payload | Discord side: is the client up, is the socket there (`ls /run/user/$(id -u)/discord-ipc-0`)? |
| Service restart-loops with `status=203/EXEC` | The script isn't executable: `chmod 755` |
| Image is an empty box | `public_url` isn't reachable from the internet, or that exercise has no still |
| Image is the app logo | The routine wasn't found by name in your state (renamed mid-workout, ad-hoc session) |
| Card disappears mid-set | The phone screen was off, or the app stayed in the background past the 45 s grace |
| Card shows no timer | The session started more than 4 h ago (a workout left open overnight) |

Useful checks:

```bash
journalctl -u opengym-discord-presence -n 20 --no-pager -o cat
ls -l /run/user/$(id -u)/discord-ipc-0        # no socket = Discord isn't up
curl -s "$OG_URL/api/health"                  # {"ok":true,...}
```

## Limitations

- The timer counts up from the workout's start; openGym doesn't know when it will end, so
  there is no progress bar.
- `exIdx`/`exTotal` counts **groups**, not exercises: a superset is one group. That is why
  the card shows a bare `4/4` — the heartbeat carries no exercise names.
- The picture is the exercise's **still** (`/exercise-media/still/<id>.webp`), not the
  animated clip: Discord renders static images only, and the clip is an `.mp4`.
- In a superset the card shows the first exercise of the group, because the heartbeat says
  which group, not which member of it.
- Discord has no "training" activity type, so the label is **Playing openGym**.
- An in-progress workout exists only while the app is open and heartbeating. Nothing is
  reported from a locked phone for more than 45 s.
- One card per Discord app; if you run this next to another presence, Discord shows the most
  recent one.

## License

MIT
