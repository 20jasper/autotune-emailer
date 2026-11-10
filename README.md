# Nightscout Autotune (minimal, self-hosted)

A tiny wrapper around the existing
[`nightscout-autotune`](https://github.com/houthacker/nightscout-autotune)
container. It runs the OpenAPS
[Autotune](https://openaps.readthedocs.io/en/latest/docs/Customize-Iterate/autotune.html)
algorithm against your Nightscout data and writes an HTML/text report.

No Azure, no web app, no database. One container, one command.

> **Safety first.** Autotune produces suggestions, not a prescription. Review every change with
> your care team before changing your pump or Loop Therapy Settings. Do not apply a large change
> all at once. This project is not medical advice.

---

## Requirements

- Docker or Podman.
- A Nightscout site with CGM, carb and bolus data.
- For Loop users: Loop should be uploading treatments to Nightscout. You must also make sure the
  **Nightscout profile** matches your Loop Therapy Settings (see below).

## Quick start

```bash
cp .env.example .env
$EDITOR .env          # set NS_HOST, auth, and TZ
./run.sh
```

Then open:

```text
reports/autotune_recommendations.html
```

The text version is `reports/autotune_recommendations.log`. The tuned OpenAPS profile is
`reports/tuned-profile.json`.

That's it. The first run pulls the upstream container and builds a tiny local image
(`nightscout-autotune-tz`) that adds timezone data. The upstream image does not include `tzdata`, so
without this `TZ` would be silently ignored and Autotune would run in UTC.

## Nightscout authentication

Use **one** of these in `.env`:

| Option | What to paste | Notes |
| --- | --- | --- |
| `NS_TOKEN` | The access token exactly as Nightscout shows it | Read-only token is enough. Create one in Nightscout → Admin tools → Subjects → Access token. |
| `NS_API_SECRET` | Your plain API secret | `run.sh` hashes it to SHA1 for you. |

If your Nightscout is publicly readable (`AUTH_DEFAULT_ROLES=readable`), you can leave both empty.
Most locked-down sites need one.

This wrapper only reads. It never uploads a profile or changes Nightscout.

## Loop users: the important bit

Autotune uses the **Nightscout profile** as its starting point and as the safety limit for every
suggestion. Standard Loop does not reliably upload your Therapy Settings to Nightscout, so the
Nightscout profile can be stale or missing.

Before running:

1. Open Loop → Settings → Therapy Settings.
2. Open your Nightscout site → Profile Editor.
3. Make sure the active Nightscout profile has the same basal schedule, ISF, carb ratio and DIA as
   Loop. Create one if needed.
4. Make sure meals are being logged as carbs (and boluses) in Nightscout. Autotune cannot tune carb
   ratio without meal data, and unannounced meals can distort basal suggestions.
5. Use the same timezone in `.env` as your pump/Loop. Use an IANA name such as
   `America/New_York`, not a fixed offset.

After the run, change Loop manually if you accept a suggestion. Changing Nightscout does not change
Loop.

If you do not want to touch your main Nightscout profile, use Nightscout → Profile Editor to create
a second profile (for example `Autotune`), copy your Loop Therapy Settings into it, and set
`NS_PROFILE=Autotune` in `.env`. Autotune will use that profile as its starting point without
changing the profile Nightscout displays.

### Good data to start with

- Start with **7 days** (`AUTOTUNE_DAYS=6`), then try **14 days** (`AUTOTUNE_DAYS=13`) once you
  trust the output.
- Avoid sick days, travel, unusual exercise or weeks with lots of missed carb entries.
- The algorithm applies small changes and caps them at your `autosens_min` / `autosens_max`
  (defaults 0.70 and 1.20).

## Reading the report

The report has three parts:

- **ISF** — suggested insulin sensitivity factor. Autotune only supports one ISF for the whole day.
- **Carb ratio** — suggested carb ratio. Also one value for the whole day.
- **Basals** — hour-by-hour suggested basal rates.

Colours follow the Autotune docs:

- **Yellow** — change of at least 10%.
- **Red** — increase of at least 20%, or decrease of at least 30%.

The **Days Missing** column is the number of days that hour had little or no usable data and was
smoothed toward neighbouring hours. Treat those rows with extra caution.

If ISF or carb ratio is unchanged, that is normal. Autotune needs at least 10 usable ISF data points
to tune ISF, and complete meal data to tune carb ratio.

Autotune outputs basal rates to three decimals. Round to what your pump/Loop accepts (often 0.01 or
0.05 U/hr).

## Options

All options live in `.env`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NS_HOST` | required | Nightscout URL, no trailing slash. |
| `NS_TOKEN` / `NS_API_SECRET` | — | Read access. Use one. |
| `AUTOTUNE_DAYS` | `6` | Days *before* yesterday. The run includes yesterday, so `6` gives a 7-day window and `13` gives a 14-day window. |
| `UAM_AS_BASAL` | `false` | Categorise unannounced meals as basal. Leave false unless you know why. |
| `TZ` | `Etc/UTC` | Pump/Loop timezone. **Set this.** |
| `NS_PROFILE` | default | Nightscout profile name to use. |
| `INSULIN_TYPE` | `rapid-acting` | `rapid-acting` (peak 75 min) or `ultra-rapid` (peak 55 min, e.g. Fiasp/Lyumjev). |
| `AUTOSENS_MIN` / `AUTOSENS_MAX` | `0.7` / `1.2` | Safety caps. |
| `MIN_5MIN_CARBIMPACT` | `8.0` | Autotune's minimum carb absorption. Leave alone unless you know why. |
| `CONTAINER_ENGINE` | auto | `docker` or `podman`. |
| `BASE_IMAGE` | Docker Hub `houthacker42/nightscout-autotune:latest` | Upstream image the local image is built from. |
| `IMAGE` | `nightscout-autotune-tz:latest` | Local image used for the run. Only override this if you know the image includes timezone data. |
| `REBUILD_IMAGE` | `false` | Rebuild the local image before running. |
| `KEEP_TEMP` | `false` | Keep the raw Nightscout JSON in a temp directory for debugging. |
| `CONTAINER_NETWORK` | — | Advanced: pass `host` when testing against a local Nightscout. |

## Run it automatically (systemd timer)

The repo includes user-level units in `systemd/`. They assume the repo is at
`~/coding/autotune`; edit the paths if yours is elsewhere.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/nightscout-autotune.service systemd/nightscout-autotune.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now nightscout-autotune.timer

# Keep the user timer running after logout/reboot:
loginctl enable-linger "$USER"
```

Check it:

```bash
systemctl --user list-timers nightscout-autotune.timer
systemctl --user start nightscout-autotune.service   # run once now
journalctl --user -u nightscout-autotune.service -f
```

The timer runs every **Sunday at 04:30** (with up to 20 minutes of jitter).
That is after Autotune's 4am→4am day boundary, so the most recent day is
complete. `Persistent=true` means a missed run is caught up after boot. The
service calls `scheduled-run.sh`, which runs `run.sh` and then emails the result.
A failed run also sends an email with the log tail, so failures are not silent.

To change the schedule, edit `OnCalendar=` in
`~/.config/systemd/user/nightscout-autotune.timer`, then run
`systemctl --user daemon-reload`.

### cron alternative

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
XDG_RUNTIME_DIR=/run/user/1000

30 4 * * 0 cd "$HOME/coding/autotune" && ./scheduled-run.sh >> reports/cron.log 2>&1
```

Replace `1000` with your `id -u` and the path with the repo location. Rootless
Podman from cron can be unreliable; the systemd user timer is the safer option.

## Email reports

Email is optional. Add the SMTP settings from `.env.example` to `.env`:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_SSL=false
SMTP_USER=you@example.com
SMTP_PASS=your-app-password
SMTP_FROM=you@example.com
SMTP_TO=you@example.com
```

Use an app-specific password, not your normal account password. `SMTP_TO` can
contain multiple comma-separated addresses.

### Gmail

1. Sign in to the Google account you want to send from.
2. Enable **2-Step Verification** at <https://myaccount.google.com/security>.
   App passwords are not available without it.
3. Open <https://myaccount.google.com/apppasswords> (or
   Security → 2-Step Verification → App passwords).
4. Create an app password named `Nightscout Autotune`.
5. Put the 16-character password in `.env`. You can paste it with or without the spaces Google
   displays; the script removes spaces from 16-character app passwords. If you prefer not to edit
   the file, run `python3 set_app_password.py` and paste it at the hidden prompt:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_SSL=false
SMTP_USER=you@gmail.com
SMTP_PASS=abcdefghijklmnop
SMTP_FROM=you@gmail.com
SMTP_TO=you@gmail.com
```

6. Test:

```bash
python3 send_report.py --dry-run   # build the email locally
python3 send_report.py             # actually send it
```

If Gmail says **“Username and Password not accepted”**, you almost certainly used your normal
Google password instead of the app password, or 2-Step Verification is off. Google Workspace
accounts can also have app passwords disabled by the administrator; a normal personal Gmail account
is easiest for this.

`SMTP_FROM` should normally be the same Gmail address as `SMTP_USER`. `SMTP_TO` can be any address
you want to receive the report at.

Test without sending:

```bash
python3 send_report.py --dry-run
# writes reports/email-preview.eml
```

Send the current report manually:

```bash
python3 send_report.py
```

The email contains:

- the HTML report inline;
- the text report and the tuned OpenAPS profile attached;
- a short **“Suggested Loop Therapy Settings”** summary (DIA, ISF, carb ratio
  and hourly basal rates).

There is no standard Loop file import for Therapy Settings. The summary is for
reading and manually entering accepted changes in
**Loop → Settings → Therapy Settings**. If a run fails, the email says so and
attaches the last run log (secrets already redacted by `run.sh`).

Email contains health data; use a private mailbox.

## How it works

`run.sh` does very little:

1. Loads `.env`.
2. Hashes a plain API secret (the container expects `NS_API_SECRET` as the SHA1 hash).
3. Builds a tiny local image from the upstream `nightscout-autotune` image, adding `tzdata` so the
   `TZ` setting is actually honoured.
4. Starts that image with a temporary bind mount.
5. The image converts your Nightscout profile to OpenAPS format, runs `oref0-autotune` day by day,
   and exports an HTML report.
6. `run.sh` copies the HTML, text report and final tuned profile into `reports/`, then deletes the
   temporary directory containing the raw Nightscout entries/treatments.

The raw Nightscout data is not left on disk. The `reports/` directory does contain your therapy
settings and recommendations, so protect it accordingly.

## Privacy

- Nightscout credentials are passed to the container as environment variables for the run. They are
  not written to `.env` by this project (you write them there yourself).
- The container output is copied to `reports/last-run.log` with the generated secret hash and token
  redacted.
- The wrapper removes the temp directory with the downloaded Nightscout JSON after each run.

## Troubleshooting

**“Nightscout rejected the credentials”**
Check whether your site is locked down. Use a token or API secret. For an API secret, paste the plain
secret; `run.sh` hashes it. If you paste an already-hashed 40-character secret, it is used as-is.

**“No BG-values” / empty report / it stops on the first day**
The container aborts if *any* day in the range has no CGM entries. This is common when you have only
just started using Nightscout, because `AUTOTUNE_DAYS` reaches back further than your data. Reduce
`AUTOTUNE_DAYS` until every day in the window has readings. Remember it counts days *before*
yesterday: `5` gives a 6-day window ending yesterday.

**Everything is shifted by a few hours**
Set `TZ` to your pump/Loop timezone, using an IANA name such as `America/New_York`. `run.sh` builds a
local image with `tzdata` because the upstream image would otherwise ignore `TZ` and run in UTC. Do
not override `IMAGE` with the upstream image unless it includes timezone data.

**“No Nightscout profile found”**
Create and activate a profile in Nightscout → Profile Editor. For Loop, copy your Therapy Settings
into it first.

**“Permission denied” creating `/tmp/autotune/settings`**
On SELinux hosts (Fedora, etc.) the bind mount needs relabelling. `run.sh` adds `:Z` automatically
when `getenforce` is available and SELinux is enabled.

**The image will not start on a Raspberry Pi / ARM**
The published image supports `linux/amd64` and `linux/arm64`. Check your architecture with
`uname -m`.

**I want to see the raw data**
Run with `KEEP_TEMP=true ./run.sh`. The temp directory path is printed at the end.

## Why not AutotuneWeb?

AutotuneWeb was the Azure-hosted web service. It is archived, and its code was designed around Azure
Batch/Storage. This wrapper runs the same OpenAPS algorithm locally and works with any Nightscout
site, including self-hosted ones.

## Want a web UI instead?

If you prefer a browser UI, [Nighttune](https://github.com/houthacker/nighttune) is the actively
maintained successor to AutotuneWeb. It can be used hosted at <https://nighttune.app> or self-hosted
with its frontend + backend containers. That is more moving parts than this wrapper, but it gives
you profile confirmation, email reports and a nicer results view.

## Development

The runtime scripts use only the Python standard library. Linting and type checking use `uv`:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uvx --from shellcheck-py shellcheck run.sh scheduled-run.sh
```

Use `uv run ruff format .` to apply formatting. The tool versions are pinned in `uv.lock`.

## Repository hygiene

`.env`, `reports/`, local experiments under `spike/`, and agent/tool state are gitignored. The
repository contains no Nightscout credentials, SMTP passwords or health data.

## Credits

- [OpenAPS oref0](https://github.com/openaps/oref0) — the Autotune algorithm.
- [houthacker/nightscout-autotune](https://github.com/houthacker/nightscout-autotune) — the container
  that converts a Nightscout profile and runs Autotune.
- [Nightscout](https://github.com/nightscout/cgm-remote-monitor) — the data source.

This wrapper is a small shell script. The heavy lifting is done by those projects.
