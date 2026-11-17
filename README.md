# opengym-discord-presence

Show your live workout from [openGym](https://gitlab.com/DuarteSantos28/opengym) as a
Discord Rich Presence card: routine, sets done, position in the session and a running
timer.

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
(bannable). So the script sits next to a Discord client — your desktop, or a headless one
on a server — and reads the workout over openGym's API.

openGym has this to read because the web app heartbeats while a workout is open:
`POST /api/activity` every 20 s with the routine name, the sets done and the position in
the session. The API keeps it **in memory only** (70 s TTL, 45 s grace if the app goes to
the background), which is exactly the granularity a presence card wants. The in-progress
workout itself is never saved server-side, so this is the only place it exists.

## Requirements

- Python 3.8+ and `pip install pypresence`
- A Discord client running and logged in on the same machine
- openGym reachable over HTTP and an **admin** user id

## The one awkward part: authentication

The only endpoint that exposes live workouts is `GET /api/admin/users` (the admin
dashboard's "training now" list). There is no public or self endpoint, so the script has
to authenticate as an admin.

It does that with the instance's own signing key, `data/secret`, the same way the API
mints its session cookie (HMAC-SHA256 over `uid:expiry:version:c`). Treat that file like
a root password: whoever has it can act as any account. Put it in the env file with mode
`600`, and rotate it (`rm data/secret` + restart the API, which signs everyone out) if it
leaks.

If you would rather not hand the key over, the alternative is patching the API to expose
`GET /api/activity` for the signed-in user — a change you would have to reapply on every
upgrade.

## Install

### 1. Create the Discord application

1. <https://discord.com/developers/applications> → **New Application** → name it
   `openGym` (this text is what appears in the card: "Playing openGym").
2. **General Information** → copy the **Application ID**.
3. **Rich Presence → Art Assets** → upload a logo with the key `opengym`
   (the key must match `DISCORD_ASSET`). Without an asset the card has no image.

### 2. Collect the three openGym values

| Value | Where |
|---|---|
| `OG_UID` | your user id: `id` in `data/db.json`, or the `state-<UID>.json` filename |
| `OG_SECRET` | `cat data/secret` (`data` is the API's data volume) |
| `OG_SV` | your user's `sv` in `data/db.json`; `0` unless you used "sign out everywhere" |

### 3. Install the script

```bash
sudo install -m 755 opengym-discord-presence.py /usr/local/bin/
pip install pypresence
```

### 4. Configure

```bash
sudo install -m 600 .env.example /etc/opengym-presence.env
sudo nano /etc/opengym-presence.env
```

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `OG_URL` | yes | `http://127.0.0.1:31180` | openGym base URL (the web container proxies `/api`) |
| `OG_UID` | yes | — | Your user id |
| `OG_SECRET` | yes | — | Contents of `data/secret` |
| `OG_SV` | no | `0` | Your user's `sv` |
| `DISCORD_CLIENT_ID` | yes | — | Application ID from step 1 |
| `DISCORD_ASSET` | no | `opengym` | Asset key for the card image |
| `POLL` | no | `20` | Seconds between polls |

### 5. Test before installing the service

```bash
set -a; . /etc/opengym-presence.env; set +a
XDG_RUNTIME_DIR=/run/user/$(id -u) opengym-discord-presence.py --once
```

`--once` prints the payload it would send (or `nada en curso`) without touching Discord:
it exercises the login, the JSON and the card text in one shot. If it works but nothing
shows up on your profile, the problem is the Discord connection, not openGym.

Start a workout in the app and run it without `--once` — the card appears within one poll
and clears by itself within ~20 s of finishing.

### 6. Run it as a service

```bash
sudo install -m 644 opengym-discord-presence.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now opengym-discord-presence
journalctl -u opengym-discord-presence -f
```

Edit the unit first if needed: `ExecStart` path, `EnvironmentFile`, `User`, and
`XDG_RUNTIME_DIR` (the runtime dir of the user running Discord — `/run/user/1000` for the
first user, `/run/user/0` for root).

No desktop session on that machine? See [docs/headless-discord.md](docs/headless-discord.md)
for running the Discord client on a virtual display (~500 MB RAM).

## Troubleshooting

| Symptom | Cause |
|---|---|
| `HTTPError 401` | `OG_SECRET`, `OG_UID` or `OG_SV` is wrong — the server signs with its own key |
| `HTTPError 403` | that user isn't an admin |
| `ConnectionRefusedError` | Discord isn't running, or `XDG_RUNTIME_DIR` points to another user's runtime dir |
| `User logged out` (error 1000) | Discord lost the session — check the client's screen and log in again |
| Card never appears, `--once` prints a payload | The Discord side: is the client up, is the socket there (`ls /run/user/$(id -u)/discord-ipc-0`)? |
| Service restart-loops with `status=203/EXEC` | The script isn't executable: `chmod 755` |
| Card disappears mid-set | The phone screen was off / the app went to background for more than 45 s |
| Card shows no timer | The session started more than 4 h ago (a workout left open overnight) |

Useful checks:

```bash
journalctl -u opengym-discord-presence -n 20 --no-pager -o cat
ls -l /run/user/$(id -u)/discord-ipc-0     # no socket = Discord isn't up
curl -s -H "Cookie: __Host-gymsid=$COOKIE" "$OG_URL/api/admin/users" | jq '.users[].live'
```

## Limitations

- The timer counts up from the workout's start; openGym doesn't know when it will end, so
  there is no progress bar.
- `exIdx`/`exTotal` counts **groups**, not exercises: a superset is one group. That is why
  the card shows a bare `4/4` instead of naming the exercise — the heartbeat doesn't carry
  exercise names.
- Discord has no "training" activity type, so the label is **Playing openGym**.
- One card per Discord app; if you run this next to another presence, Discord shows the
  most recent one.
- An in-progress workout exists only while the app is open and heartbeating. Nothing is
  reported from a locked phone for more than 45 s.

## License

MIT
