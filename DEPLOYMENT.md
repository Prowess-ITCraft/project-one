# Deploying Project One

How to put Project One on a server for real use, from an empty machine to the first person
signing in. Follow the steps in order. Each step says how to check it worked before you move on.

The [operations guide](docs/guides/03-operations-guide.md) has the detail behind each step
(every setting, key rotation, monitoring, routine tasks). This page is the path through it.

## What you are deploying

Everything runs in Docker on one server. Only the proxy is reachable from outside.

```
 people (browser, phone)
          |  https://p1.your-domain
          v
 +------------------+       +-------------------------------------------------------+
 | proxy (nginx)    | ----> | web (Next.js)   api (FastAPI)   worker + beat (Celery) |
 | 80, 443, 9597    |       | postgres   redis (Valkey)   minio (files)   clamav     |
 +------------------+       +-------------------------------------------------------+
                                  internal network only, nothing published
```

- **Port 443** serves the app over HTTPS. **Port 80** only answers certificate checks and sends
  everything else to HTTPS. Nothing else is published (ADR 0030). Only with a load balancer in
  front (option C) is **port 9597** opened as well, for plain HTTP from the load balancer.
- The database, file storage and cache are never reachable from outside. Files are served to
  browsers through the app itself, with short-lived signed links.
- Backups run every night at 21:00 UTC (02:30 India time) into the `p1-backups` storage bucket.

## 1. What you need first

| Item | Minimum | Notes |
| --- | --- | --- |
| Server | 4 vCPU, 8 GB RAM, 60 GB SSD | Ubuntu Server 24.04 LTS or 22.04 LTS. ClamAV alone needs about 1.5 GB of memory |
| Domain name | One, for example `p1.itcraft.net.in` | An A record pointing at the server's public IP address |
| Open ports | 22 (SSH, your office only), 80, 443 | Nothing else. 9597 only if a load balancer is in front |
| Email account | SMTP host, port, user, password | Sends visit codes to customers, waiver links and notices. Without it, field check-ins cannot work |
| A password manager | Company vault | For the `.env` file and the first admin's recovery codes |

Decide now how HTTPS will work. You will need it in step 5.

- **A. Let's Encrypt**: free, renews itself. The server must be reachable from the internet on port 80.
- **B. Your own certificate**: from the company's provider. You renew it yourself.
- **C. A load balancer** (cloud or office) already handles HTTPS and forwards plain HTTP to port 9597.

## 2. Prepare the server

Sign in over SSH as a user with `sudo`, then install Docker from Docker's own repository:

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER   # then sign out and back in
```

Turn on the firewall (replace the address with your office's public IP):

```bash
sudo ufw allow from 203.0.113.10 to any port 22 proto tcp
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable
```

**Check:** `docker run --rm hello-world` prints "Hello from Docker!".

## 3. Get the code

```bash
sudo mkdir -p /srv/project-one && sudo chown $USER /srv/project-one
git clone <repository address> /srv/project-one
cd /srv/project-one
```

Every command from here on runs in `/srv/project-one`.

## 4. Create the settings file (.env)

One command writes `.env` with strong random secrets. Give it your domain and email details:

```bash
python3 scripts/new_env.py \
  --domain p1.itcraft.net.in \
  --smtp-host smtp.your-provider.com --smtp-port 587 \
  --smtp-user no-reply@itcraft.net.in --smtp-from no-reply@itcraft.net.in
```

It asks for the email password without showing it. If a load balancer handles HTTPS (option C),
add `--proxy conf.d`.

Then, straight away:

1. **Copy `.env` into the company password manager.** `P1_FERNET_KEYS` encrypts personal data
   in the database; if it is lost, that data cannot be read again, even from a backup.
2. Never commit `.env` or send it by email or chat.

The app refuses to start in production with unsafe settings: a development secret, an `http://`
or `localhost` address, missing email. The error names the setting to fix.

**Check:** `grep -c = .env` prints 25, and `ls -l .env` shows `-rw-------`.

## 5. HTTPS certificate

Set the shorthand used in the rest of this guide (add it to `~/.bashrc` to keep it):

```bash
alias p1='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

**A. Let's Encrypt.** With nothing else running on port 80, get the first certificate:

```bash
p1 --profile tls run --rm -p 80:80 --entrypoint certbot certbot certonly --standalone \
  -d p1.itcraft.net.in --cert-name project-one -m it@itcraft.net.in --agree-tos -n
```

From now on, start the stack with `--profile tls` so the `certbot` service renews it.

**B. Your own certificate.** Copy the full chain (your certificate first, then the
intermediates) and the private key into place:

```bash
mkdir -p infra/nginx/tls/live/project-one
cp fullchain.pem infra/nginx/tls/live/project-one/fullchain.pem
cp privkey.pem   infra/nginx/tls/live/project-one/privkey.pem
chmod 600 infra/nginx/tls/live/project-one/privkey.pem
```

**C. Load balancer.** No certificate here. Add the load balancer file to the shorthand, so
port 9597 is published, then point the load balancer at port 9597 of this server and allow that
port only from the load balancer:

```bash
alias p1='docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.lb.yml'
```

**Check (A and B):** `ls infra/nginx/tls/live/project-one/` lists `fullchain.pem` and `privkey.pem`.

## 6. Build and start

```bash
p1 build                                  # about 10 minutes the first time
p1 up -d                                  # add --profile tls for option A
p1 ps
```

On the first start ClamAV downloads its virus database, which takes up to five minutes; the API
waits for it. The `migrate` job creates the database tables and storage buckets, then exits.

**Check:** after a few minutes `p1 ps` shows `api`, `worker`, `beat`, `web`, `postgres`, `redis`
and `clamav` as `healthy`, `migrate` as `Exited (0)`, and:

```bash
curl -sI https://p1.itcraft.net.in/healthz | head -1      # HTTP/2 200
curl -sI http://p1.itcraft.net.in/ | head -1               # 301, on to https
```

## 7. First admin and starting data

Create the first admin. It asks for a password: at least 12 characters, not containing the
name or email.

```bash
p1 exec api python -m app.cli create-admin --email it@itcraft.net.in --name "IT Admin" --initials IA
p1 exec api python -m app.cli seed      # catalogue items, prices, rules and templates
```

Then, in a browser:

1. Open `https://p1.itcraft.net.in` and sign in as that admin.
2. Set up the authenticator app when asked, and **save the recovery codes in the password
   manager**.
3. Open **Accounts** and create everyone's account with their roles. Give each person their
   temporary password in person.
4. Sign in as the Director once, open **Certificate** in the sidebar, and check the wording and
   the IITPL stamp.
5. Optional: add old BOQs and PrismSuite reports to the library by copying them into
   `./inbox` on the server; the worker reads that folder every five minutes.

Do not run `seed-demo` or `demo-projects` here. They are for development and refuse to run
in production.

## 8. Check everything works

Go through this list once, with a real phone for the last two items:

- [ ] `https://p1.itcraft.net.in` shows the sign-in page with a valid padlock
- [ ] An admin can sign in with the authenticator code
- [ ] Creating a test project and uploading a PrismSuite report works (this also proves the
      virus scanner and file storage)
- [ ] A test email arrives: a visit code sent to your own address as the customer contact
- [ ] A field engineer can sign in on a phone and see **My tasks**
- [ ] A photo taken on the phone appears on the task page
- [ ] `p1 exec worker python -m app.cli backup` finishes, and a restore drill passes:
      `python3 scripts/restore_drill.py --prod` (it restores into a throwaway database and
      compares every table; it never touches the live one)

## 9. Backups off the server

The nightly backup is stored inside this server's file storage. That protects against mistakes,
not against losing the server. Copy it somewhere else every day, for example to a mounted
backup disk or network share at `/mnt/backup`. The app copies only backups that are not there
yet:

```bash
sudo mkdir -p /mnt/backup/project-one
sudo chown 10001 /mnt/backup/project-one      # the user the app runs as inside its containers
```

```bash
# /etc/cron.d/project-one-backup: copy new backups off the server at 04:00 India time
30 22 * * * root cd /srv/project-one && docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --no-deps -T -v /mnt/backup/project-one:/out worker python -m app.cli backup-export --out /out >> /var/log/project-one-backup.log 2>&1
```

**Check:** the next morning, `ls -R /mnt/backup/project-one` shows a `.dump` file dated last
night, and `tail /var/log/project-one-backup.log` says how many were copied.

Keep a copy of `.env` with the backups (in the password manager, not on the same disk).
Practise a restore at least once before go-live and after any large data import.

## 10. Day to day

| Task | Command |
| --- | --- |
| See what is running | `p1 ps` |
| Follow the logs | `p1 logs -f api worker` |
| Restart one part | `p1 restart api` |
| Take a backup now | `p1 exec worker python -m app.cli backup` |
| Unlock a person | In the app: **Accounts**, their name, **Unlock** |
| Monitoring (Grafana) | `p1 --profile monitoring up -d`. From your computer: `ssh -L 9604:localhost:9604 you@server`, then open `http://localhost:9604` (user `admin`, password `P1_GRAFANA_PASSWORD` from `.env`) |
| API reference | `https://p1.itcraft.net.in/docs`; every route is listed in [docs/API_ROUTES.md](docs/API_ROUTES.md) |

## 11. Updating to a new version

```bash
cd /srv/project-one
p1 exec worker python -m app.cli backup         # 1. back up first
git pull                                          # 2. new code
sed -i 's/^P1_VERSION=.*/P1_VERSION=1.1.0/' .env  # 3. a new image tag
p1 build && p1 up -d                              # 4. migrations run before the api starts
curl -sI https://p1.itcraft.net.in/readyz | head -1
```

**Rolling back:** set `P1_VERSION` back to the previous tag and run `p1 up -d`. The old images
are still on the server. If the new version changed the database, restore the backup from
step 1 as well (operations guide, section 5).

## 12. Security checklist

- [ ] `.env` is in the password manager and readable only by its owner (`chmod 600 .env`)
- [ ] SSH only from the office address, with keys, not passwords
- [ ] Only ports 80 and 443 are open to the internet (`sudo ufw status`)
- [ ] Every Director and Admin has the authenticator set up, and their recovery codes are saved
- [ ] The development login `adi@test.com` does not exist (it is never created in production)
- [ ] Backups are copied off the server every day, and a restore has been practised
- [ ] Ubuntu security updates are on: `sudo apt-get install unattended-upgrades`
- [ ] The interactive API reference can be hidden with `P1_API_DOCS=false` in `.env` if the
      server is open to the internet and nobody outside the team needs it

## 13. When something goes wrong

For anything serious (site down, data lost, a possible break-in), follow the
[incident runbook](docs/runbooks/incident.md). Quick fixes:

| What you see | What to do |
| --- | --- |
| `api` keeps restarting, log says "Unsafe configuration" | The message names the setting. Fix it in `.env`, then `p1 up -d` |
| `p1 up` stops with "set P1_... in .env" | A required secret is missing from `.env`. Run step 4 again on a fresh copy, or add the line |
| The page loads but sign-in goes back to the sign-in page | The site was opened over `http://`. Use `https://`; sign-in cookies only travel over HTTPS |
| "Too many requests" for everyone in the office | Someone is retrying in a loop. The limits allow 60 sign-ins a minute per address; check `p1 logs proxy` |
| Uploads fail with "scanner unavailable" | ClamAV is still starting (`p1 ps`), or the server is short of memory (`free -h`) |
| Customers do not get visit codes | Check the SMTP settings in `.env`, then `p1 logs worker` for the sending error |
| Browser warns about the certificate | Option A: `p1 --profile tls logs certbot`. Option B: the files in `infra/nginx/tls/live/project-one/` |
| Photos or downloads do not open | Leave `P1_S3_PUBLIC_ENDPOINT_URL` empty so files go through the app |

For anything else, the [operations guide](docs/guides/03-operations-guide.md) has the full
troubleshooting table, and `p1 logs` shows what each service is doing.
