# Incident runbook

What to do when Project One is down, wrong, or possibly broken into. Commands use the `p1`
shorthand from [DEPLOYMENT.md](../../DEPLOYMENT.md), section 5, run in `/srv/project-one`.

## Who does what

| Role | Person | Does |
| --- | --- | --- |
| First responder | Technical lead (Aditya Kumar) | Checks, fixes, rolls back, keeps the log |
| Decides on customers | Director (Satish Agadi) | Approves anything said to customers, decides on data restores |
| Admin | Whoever holds the Admin role | Locks accounts, resets passwords and authenticators |

Write each person's phone number here once, and keep this page printed by the server rack.

## How serious is it

| Level | Means | Examples | Respond |
| --- | --- | --- | --- |
| 1 | Nobody can work, or data may be exposed | Site down; signs of a break-in; data deleted | At once, any hour. Tell the Director |
| 2 | One part broken for everyone | Uploads fail; no emails, so no visit codes; sign-in fails for a role | Within the working hour |
| 3 | One person or one screen | A locked account; a page error for one project | Same day |

## The first 15 minutes (every incident)

1. **Start a log.** A note with the time, what was reported, by whom. Add every step you take.
2. **See it yourself.** Open `https://p1.itcraft.net.in` and try the thing that fails.
3. **Look at the stack:**
   ```bash
   p1 ps                                   # anything not "healthy"? migrate should be "Exited (0)"
   curl -sI https://p1.itcraft.net.in/readyz | head -1
   p1 logs --since 30m api worker | grep -iE "error|unsafe|refused" | tail -40
   df -h / && free -h                      # full disk or no memory explains a lot
   ```
4. **Decide the level** (table above). Level 1: phone the Director now.
5. **Tell the team** on the office group: what is affected, that it is being worked on, and when
   the next update comes (template below).

## Common incidents

### The site does not open

- `p1 ps` shows `proxy` stopped: `p1 up -d proxy`, then `p1 logs proxy`. A certificate problem
  shows as "cannot load certificate": see DEPLOYMENT.md, section 5.
- `api` restarting in a loop: `p1 logs api | tail -30`. "Unsafe configuration" names the
  setting in `.env` to fix. A database error: check `postgres` below.
- Everything healthy but the browser cannot connect: DNS or firewall. `dig p1.itcraft.net.in`
  must show the server's address; `sudo ufw status` must allow 80 and 443.

### Nobody can sign in

- "Too many requests": wait a minute. If it keeps happening for the whole office, something is
  retrying in a loop: `p1 logs proxy | grep " 429 " | tail`.
- Sign-in goes back to the sign-in page: someone is using `http://`. Use `https://`.
- Directors and admins cannot pass the code step: the server clock is wrong, so every
  authenticator code fails. `timedatectl` must say "synchronized: yes".

### One person cannot sign in

An admin opens **Accounts**, the person's name, then **Unlock**, **Reset password**, or
**Reset authenticator** (a lost phone). Hand over the new temporary password in person.

### No emails, so no visit codes for field engineers

```bash
p1 logs --since 1h worker | grep -i smtp | tail
```

Usually the email password changed or the provider blocked the sender. Fix `P1_SMTP_*` in `.env`,
then `p1 up -d`. Waiting emails are sent automatically once it works. Meanwhile engineers can
continue the steps that do not need a code.

### Uploads fail

- "Scanner unavailable": `p1 ps clamav`. It needs about 1.5 GB of memory; `free -h`. Restart
  with `p1 restart clamav` and wait up to five minutes.
- Storage full: `df -h`. Free space, or add a disk, before anything else.

### The disk is full

```bash
docker system df                 # what Docker is using
docker image prune -f            # old images from earlier versions (keep the current one)
```

Never delete the `project-one_pgdata` or `project-one_miniodata` volumes: they are the database
and the files.

### A new version broke something

Roll back (DEPLOYMENT.md, section 11): set `P1_VERSION` in `.env` to the previous tag and run
`p1 up -d`. If the new version changed the database and the old one does not start, restore
the backup taken before the update (below).

## Suspected break-in or account misuse (level 1)

1. **Contain first.** In **Accounts**, deactivate the suspected account and use **Sign out
   everywhere** on it. If an admin account is suspected, have another admin do this.
2. **Keep the evidence.** Do not delete anything. Copy the logs:
   ```bash
   p1 logs --since 72h > /root/incident-$(date +%F).log
   ```
   The audit log in the app shows who did what. Check nobody has altered it: signed in as an
   admin, open `https://p1.itcraft.net.in/docs`, find `GET /api/v1/audit-log/verify`, and
   run it. It reports whether the chain of entries is intact.
3. **Rotate secrets** if the server itself may be affected: new `P1_JWT_SIGNING_KEYS` signs out
   everyone; database and storage passwords next. Add new keys at the front of the list, as in
   the operations guide, "Key rotation". Never remove `P1_FERNET_KEYS` entries that encrypted
   existing data.
4. **Tell the Director the same day.** Personal data may be involved: the Director decides who
   must be told, and when.

## Restoring from a backup (data lost or damaged)

Only with the Director's agreement: everything after the backup is lost.

1. Take a fresh backup of the current state first: `p1 exec worker python -m app.cli backup`.
2. Prove the backup you will restore from is good: `python3 scripts/restore_drill.py --prod`.
3. Run the commands from the operations guide, section 5, "Restore drill by hand", on the
   live server. That section says to practise on a spare machine first; this is the real
   restore it prepares you for, so here it is the live database on purpose.
4. Check sign-in, the dashboard, and the latest project you expect to see.

## Messages

To staff (office group):

> Project One: [what is not working] since [time]. We are working on it. Next update at [time].
> Until then, [what people can do instead].

When fixed:

> Project One is working again since [time]. Cause: [one line]. Anything you saved while it was
> down [is safe / needs to be entered again: list].

To a customer (only with the Director's approval):

> Our project system had a problem on [date] between [times]. [Your data was not affected / What
> happened to your data]. [What we are doing]. Contact [name] with any questions.

## Afterwards (within a week)

Write five lines in [docs/NOTES.md](../NOTES.md): what happened, the impact, the cause, what fixed
it, and what will stop it happening again. Add that last item to [docs/TASKS.md](../TASKS.md).
