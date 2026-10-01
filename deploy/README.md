# VM deployment

This runbook assumes a Linux VM with systemd and a deployment directory of
`/opt/bombaclat`. It keeps the process under a dedicated unprivileged user,
loads secrets from `/etc/bombaclat/bombaclat.env`, writes runtime data under
`/opt/bombaclat/data`, and restarts only after an unexpected failure.

The project currently uses a user-account/self-bot client. That is not
Discord's supported production integration. This runbook does not bypass
CAPTCHAs or account protections. The safer long-term deployment is an
official bot account using OAuth2.

## Install

From the VM:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv rsync
sudo useradd --system --home /opt/bombaclat --shell /usr/sbin/nologin bombaclat || true
sudo install -d -o bombaclat -g bombaclat -m 0750 /opt/bombaclat/data
sudo install -d -o root -g bombaclat -m 0750 /etc/bombaclat
```

Copy the repository to `/opt/bombaclat` without copying your development
`.env`, virtual environment, or local database:

```bash
sudo rsync -a --delete \
  --exclude '.env' --exclude '.venv' --exclude 'data/' \
  ./ /opt/bombaclat/
sudo chown -R bombaclat:bombaclat /opt/bombaclat
sudo chmod 0700 /opt/bombaclat/data
sudo -u bombaclat python3 -m venv /opt/bombaclat/.venv
sudo -u bombaclat /opt/bombaclat/.venv/bin/python -m pip install --upgrade pip
sudo -u bombaclat /opt/bombaclat/.venv/bin/pip install \
  --index-url https://pypi.org/simple \
  -r /opt/bombaclat/requirements.txt
```

Install the secret environment file separately:

```bash
sudo install -o root -g bombaclat -m 0640 \
  /opt/bombaclat/deploy/bombaclat.env.example \
  /etc/bombaclat/bombaclat.env
sudoedit /etc/bombaclat/bombaclat.env
```

At minimum, set `DISCORD_TOKEN`, `GEMINI_API_KEY`, and the real `OWNER_ID`.
Keep `DASHBOARD_ENABLED=false` for a service. `DB_PATH` and `LOG_PATH` should
remain absolute paths under `/opt/bombaclat/data`.

## Start the service

```bash
sudo install -o root -g root -m 0644 \
  /opt/bombaclat/deploy/bombaclat.service \
  /etc/systemd/system/bombaclat.service
sudo systemctl daemon-reload
sudo systemctl enable --now bombaclat
sudo systemctl status bombaclat
sudo journalctl -u bombaclat -f
```

The service exits with status `78` for invalid configuration and will not
restart-loop on missing required secrets. Unexpected runtime failures are
restarted after 15 seconds.

## Backups

Install the backup units and create their destination:

```bash
sudo install -d -o bombaclat -g bombaclat -m 0700 /var/lib/bombaclat/backups
sudo install -o root -g root -m 0644 \
  /opt/bombaclat/deploy/bombaclat-backup.service \
  /etc/systemd/system/bombaclat-backup.service
sudo install -o root -g root -m 0644 \
  /opt/bombaclat/deploy/bombaclat-backup.timer \
  /etc/systemd/system/bombaclat-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now bombaclat-backup.timer
sudo systemctl start bombaclat-backup.service
ls -l /var/lib/bombaclat/backups
```

The backup uses SQLite's online backup API, verifies integrity, keeps the
newest 14 copies, and never needs to stop Bombaclat.

## Operations

```bash
sudo systemctl restart bombaclat
sudo systemctl stop bombaclat
sudo systemctl status bombaclat
sudo journalctl -u bombaclat --since today
tail -f /opt/bombaclat/data/bot.log
```

If Discord reports a CAPTCHA, Bombaclat's persistent safety guard stops
outbound and account-changing retries, including after service restarts.
Handle verification manually, inspect `!captcha status`, and use
`!captcha acknowledge` only after the account is clear. Do not add a CAPTCHA
solver or retry loop.
