# Deploy runbook

All of these are in [DEPLOYMENT.md](../../DEPLOYMENT.md):

- Server setup (Docker on boot, firewall, SSH keys only, automatic updates, VPN): section 2.
- First deployment: sections 3 to 8. Migrations run in the `migrate` job before the API starts.
- Updates and rollback to the previous image tag: section 11.
- Backups off the server and the restore drill (`scripts/restore_drill.py --prod`): sections 8
  and 9. Restoring the live database: [operations guide](../guides/03-operations-guide.md),
  section 5.

Also:

- When something goes wrong: [incident runbook](incident.md).
- Every setting, key rotation, monitoring and routine tasks: the
  [operations guide](../guides/03-operations-guide.md), sections 3 to 8.
