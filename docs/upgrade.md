# Upgrading and rolling back Insight

Insight keeps everything (accounts, sources, credentials, history and findings) in the `insight-data` Docker volume, so replacing the image keeps it. Database schema migrations are forward-only. **Insight backs up the database automatically before applying any migration**, to `/data/backups/insight-v<old version>-<time>.db` inside the volume.

Run these steps over SSH as `50n-admin` on the appliance, in `/opt/insight`.

## Upgrade

1. Note the running version (**Engineer** overview, or `docker compose images`).
2. Get the new image.

   With internet on board:

   ```bash
   sed -i 's/^INSIGHT_TAG=.*/INSIGHT_TAG=<new version>/' .env
   ```

   ```bash
   docker compose pull
   ```

   Without internet, copy the release tarball across (USB stick or the NAS), then:

   ```bash
   docker load -i insight-<new version>.tar
   ```

   ```bash
   sed -i 's/^INSIGHT_TAG=.*/INSIGHT_TAG=<new version>/' .env
   ```

3. Recreate the container with the new image:

   ```bash
   docker compose up -d
   ```

4. Check it is healthy and the version is the new one:

   ```bash
   docker compose ps
   ```

   ```bash
   docker compose logs --tail=50 insight
   ```

   The log shows any migration applied, and the name of the backup taken first.

## Roll back

Roll back if the new version misbehaves.

1. Stop Insight:

   ```bash
   docker compose stop insight
   ```

2. **If the upgrade applied a migration**, restore the backup taken just before it. List the backups (the newest is last):

   ```bash
   docker compose run --rm insight backups
   ```

   Restore the one taken at the upgrade. Insight keeps a copy of the database it replaces:

   ```bash
   docker compose run --rm insight restore-backup <backup file>
   ```

   If no migration ran (no new backup file), skip this step: the database is unchanged.

3. Point back at the previous version and start it:

   ```bash
   sed -i 's/^INSIGHT_TAG=.*/INSIGHT_TAG=<previous version>/' .env
   ```

   ```bash
   docker compose up -d
   ```

An older Insight refuses to start on a database a newer version has migrated, and says so in its log, rather than risking damage. Restoring the backup (step 2) is what makes the rollback work.

Anything recorded between the upgrade and the rollback is lost when you restore a backup. This is usually a few minutes of readings.
