# IdentityOps Lab: Setup and Configuration

This guide builds the lab from scratch in one Ubuntu VM. For what the lab is and how to demo it, see the main README.

## 1. Environment and assumptions

> **Lab only.** Run this only on an isolated, trusted network (for example a local VM). Kibana (5601) and Keycloak (8080) are reachable from the local network without hardening, and Elasticsearch has authentication turned off.

| Item | Value used in this guide |
|---|---|
| Hypervisor | UTM on an Apple Silicon Mac (any hypervisor works) |
| Guest OS | Ubuntu Server 24.04 LTS, ARM64 (use amd64 on Intel) |
| Resources | 4 vCPU, 10 GB RAM (8 GB minimum), 64 GB disk |
| Network | UTM Shared Network, subnet `192.168.64.0/24` |
| VM address | `192.168.64.10` (static) |
| Hostname / FQDN | `dc1` / `dc1.lab.internal` |
| AD realm / NetBIOS domain | `LAB.INTERNAL` / `LAB` |
| Project folder | `~/identityops-lab` |

Adjust the addresses if your network differs, and use them consistently everywhere below.

**Ports**

| Service | Port | Reachable from |
|---|---|---|
| Samba AD (LDAP, LDAPS, DNS, Kerberos) | 389, 636, 53, 88 | the VM and the local network |
| MySQL | 3306 | VM only (bound to 127.0.0.1) |
| Elasticsearch | 9200 | VM only (bound to 127.0.0.1) |
| Kibana | 5601 | local network |
| Keycloak | 8080 | local network |

## 2. Create the VM

1. Download `ubuntu-24.04-live-server-arm64.iso` from ubuntu.com.
2. In UTM choose **Create a New Virtual Machine, Virtualize, Linux** and select the ISO.
3. Set memory to 10240 MB, 4 CPU cores and a 64 GB disk. Keep **Shared Network**.
4. Run the installer, tick **Install OpenSSH server**, and create your user.
5. When it finishes, clear the CD/DVD drive in UTM and reboot. Then connect with `ssh <user>@<vm-ip>`.

## 3. Prepare Ubuntu

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y git curl jq unzip python3-venv python3-pip docker.io docker-compose-v2 mysql-client
sudo usermod -aG docker $USER            # log out and back in afterwards
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-es.conf && sudo sysctl --system
```

**Static IP.** Find the interface name with `ip -br a` (usually `enp0s1`), then edit `/etc/netplan/50-cloud-init.yaml`:

```yaml
network:
  version: 2
  ethernets:
    enp0s1:
      dhcp4: false
      addresses: [192.168.64.10/24]
      routes:
        - to: default
          via: 192.168.64.1
```

Apply it with `sudo netplan apply`, then reconnect on the new address. DNS is configured later, because Samba provides it.

**Hostname:**

```bash
sudo hostnamectl set-hostname dc1.lab.internal
# in /etc/hosts delete the "127.0.1.1 ..." line and add:
# 192.168.64.10  dc1.lab.internal  dc1
```

## 4. Get the project and configure it

```bash
git clone <this-repo-url> identityops-lab && cd identityops-lab
cp .env.example .env
mkdir -p logs
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Fill in `.env`. It is excluded from Git and holds every secret.

| Variable | Meaning |
|---|---|
| `AD_HOST` | AD server name, `dc1.lab.internal` |
| `AD_BIND` | Service account used by the engine, `svc-jml@lab.internal` |
| `AD_PASS` | Password of `svc-jml` |
| `TEMP_PASSWORD` | Initial password for new accounts (forced change at first logon). Must meet AD complexity rules |
| `DB_PASS` | Password of the MySQL `jml` user |
| `DB_ROOT_PASS` | MySQL root password |
| `KC_ADMIN_PASS` | Keycloak admin password |

Load it into a shell with `set -a; . ./.env; set +a`.

## 5. Active Directory (Samba)

Install the packages:

```bash
sudo DEBIAN_FRONTEND=noninteractive apt install -y acl attr samba samba-dsdb-modules samba-vfs-modules \
  winbind libpam-winbind libnss-winbind libpam-krb5 krb5-config krb5-user dnsutils
```

Free port 53 for Samba's DNS and stop the file-server daemons:

```bash
sudo systemctl disable --now systemd-resolved smbd nmbd winbind
sudo systemctl mask smbd nmbd winbind
sudo rm /etc/resolv.conf && echo 'nameserver 1.1.1.1' | sudo tee /etc/resolv.conf   # becomes the DNS forwarder
```

Provision the domain:

```bash
sudo mv /etc/samba/smb.conf /etc/samba/smb.conf.orig
sudo samba-tool domain provision --use-rfc2307 --realm=LAB.INTERNAL --domain=LAB \
  --server-role=dc --dns-backend=SAMBA_INTERNAL --adminpass='<choose-a-strong-password>'
sudo cp /var/lib/samba/private/krb5.conf /etc/krb5.conf
sudo systemctl unmask samba-ad-dc && sudo systemctl enable --now samba-ad-dc
printf 'nameserver 192.168.64.10\nsearch lab.internal\n' | sudo tee /etc/resolv.conf
```

Verify:

```bash
host -t SRV _ldap._tcp.lab.internal
kinit administrator@LAB.INTERNAL && klist
sudo samba-tool domain level show
```

**Lab-only setting.** Keycloak binds over plain LDAP, which Samba refuses by default. Add this line under `[global]` in `/etc/samba/smb.conf` and restart Samba:

```
ldap server require strong auth = no
```

```bash
sudo systemctl restart samba-ad-dc
```

**OU structure and service accounts** (run with `.env` loaded):

```bash
sudo samba-tool ou create "OU=Corp"
for ou in Users Groups Disabled ServiceAccounts; do sudo samba-tool ou create "OU=$ou,OU=Corp"; done

sudo samba-tool user create svc-jml "$AD_PASS" --userou="OU=ServiceAccounts,OU=Corp"
sudo samba-tool user setexpiry svc-jml --noexpiry
sudo samba-tool group addmembers "Domain Admins" svc-jml          # lab shortcut, see section 15

sudo samba-tool user create svc-keycloak '<choose-a-password>' --userou="OU=ServiceAccounts,OU=Corp"
sudo samba-tool user setexpiry svc-keycloak --noexpiry
```

Remember the `svc-keycloak` password, because you enter it in Keycloak later.

## 6. Start the Docker stack

```bash
cd infra
docker compose --env-file ../.env up -d
docker compose --env-file ../.env ps
cd ..
```

Five containers should be running: MySQL, Keycloak, Elasticsearch, Kibana and Filebeat. All have `restart: unless-stopped`, so they come back after a reboot.

- MySQL creates the HR schema and the seed employees from `hr-source/schema.sql` on its **first** start only. To reset it, run `docker compose --env-file ../.env down -v` (this deletes all stack data) and start again.
- Elasticsearch needs about a minute to become ready, and Kibana a little longer.
- If an image download fails with a registry error such as a 502, retry. Layers already pulled are cached.

Check the services:

```bash
mysql -h127.0.0.1 -ujml -p"$DB_PASS" hr -e 'SELECT employee_id, first_name, last_name, job_title FROM employees;'
curl -s localhost:9200 | head -3
```

## 7. Run the engine and schedule it

```bash
./run.sh
tail -5 logs/provisioning.jsonl              # user_created, group_added, run_complete
sudo samba-tool user list
```

`run.sh` loads `.env`, waits up to 60 seconds for MySQL (which matters right after a VM boot), runs `provisioning/jml.py`, then `provisioning/snapshot.py`, and prints timestamps for the cron log.

Schedule it with `crontab -e`. `flock` stops two runs from overlapping:

```
*/5 * * * * flock -n /tmp/identityops.lock /home/<user>/identityops-lab/run.sh >> /home/<user>/identityops-lab/logs/cron.log 2>&1
```

After 5 to 10 minutes, `tail logs/cron.log` should show `run start` and `run done` lines with no traceback.

## 8. Kibana dashboard

Import the saved dashboard:

```bash
curl -s -X POST 'http://localhost:5601/api/saved_objects/_import?overwrite=true' \
  -H 'kbn-xsrf: true' --form file=@monitoring/dashboard.ndjson
```

The response should contain `"success":true`. Open `http://<vm-ip>:5601`, go to **Dashboards** and open **IdentityOps**.

The dashboard has four panels: error count, errors by kind, events over time (split by event), and the audit trail. It depends on a data view for `identityops-*` with `@timestamp` as the time field, which the import creates.

To re-export it after changes:

```bash
curl -s -X POST 'http://localhost:5601/api/saved_objects/_export' \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' \
  -d '{"type":["dashboard"],"includeReferencesDeep":true}' -o monitoring/dashboard.ndjson
```

The last line of the file should show `"exportedCount":3` and `"missingRefCount":0`.

## 9. Keycloak

Open `http://<vm-ip>:8080`, choose **Administration Console**, and log in as `admin` with `KC_ADMIN_PASS`.

Before you start, check from the VM that the container can reach Samba:

```bash
cd infra && docker compose --env-file ../.env exec keycloak bash -c 'echo > /dev/tcp/host.docker.internal/389 && echo "port 389 reachable"'; cd ..
```

1. **Realm.** From the realm dropdown choose **Create realm** and name it `lab`.
2. **LDAP provider.** Go to **User federation, Add LDAP providers**:

   | Field | Value |
   |---|---|
   | UI display name | `lab-ad` |
   | Vendor | Active Directory |
   | Connection URL | `ldap://host.docker.internal:389` |
   | Bind type | simple |
   | Bind DN | `CN=svc-keycloak,OU=ServiceAccounts,OU=Corp,DC=lab,DC=internal` |
   | Bind credentials | the `svc-keycloak` password |
   | Edit mode | **READ_ONLY** |
   | Users DN | `OU=Users,OU=Corp,DC=lab,DC=internal` |
   | Username LDAP attribute | `sAMAccountName` |
   | RDN LDAP attribute | `cn` |
   | UUID LDAP attribute | `objectGUID` |
   | User object classes | `person, organizationalPerson, user` |

   Use **Test connection** and **Test authentication**, then save and run **Action, Sync all users**. Optionally enable periodic full sync (for example every 300 seconds).

3. **Group mapper.** On the provider's **Mappers** tab choose **Add mapper**:

   | Field | Value |
   |---|---|
   | Name | `groups` |
   | Mapper type | `group-ldap-mapper` |
   | LDAP Groups DN | `OU=Groups,OU=Corp,DC=lab,DC=internal` |
   | Group name LDAP attribute | `cn` |
   | Group object classes | `group` |
   | Preserve group inheritance | Off |
   | Membership LDAP attribute | `member` |
   | Membership attribute type | DN |
   | Mode | READ_ONLY |
   | User groups retrieve strategy | `LOAD_GROUPS_BY_MEMBER_ATTRIBUTE` |
   | Drop non-existing groups during sync | On |

   Save, then use **Sync LDAP Groups to Keycloak**.

4. **Email requirement.** Under **Realm settings, User profile, email**, turn **Required field** off. Without this, logins fail with "Account is not fully set up".
5. **Client.** Under **Clients, Create client**: Client type OpenID Connect, Client ID `demo-app`, **Client authentication Off**, **Standard flow On**, **Direct access grants On**, redirect URI `http://localhost/*`.
6. **Group claim.** Open `demo-app`, then **Client scopes, demo-app-dedicated, Configure a new mapper, Group Membership**. Name it `groups`, token claim name `groups`, **Full group path Off**, and add it to the ID token, access token and userinfo.

Users sign in at `http://<vm-ip>:8080/realms/lab/account`. The master realm login is only for the admin.

**Token check** (the helper file is in the repo):

```bash
source kc_token.sh
sudo samba-tool user setpassword apetrova --newpassword='<a-password-you-choose>'
kc_token apetrova      # shows preferred_username and groups
```

## 10. Verification checklist

```bash
systemctl is-active samba-ad-dc                                          # active
docker ps --format 'table {{.Names}}\t{{.Status}}'                       # five containers up
python -W ignore provisioning/jml.py && tail -1 logs/provisioning.jsonl  # run_complete
python -W ignore provisioning/snapshot.py && echo "snapshot OK"
curl -s 'localhost:9200/identityops-*/_count'; echo                      # count grows over time
```

Then confirm that new events appear in the Kibana dashboard, and that `tail logs/cron.log` shows clean runs. The demo in the main README is also a good end-to-end test.

## 11. Operating the lab

**Start and stop.** Docker containers restart by themselves after a reboot, and Samba is enabled as a systemd service. To stop and start everything manually:

```bash
cd ~/identityops-lab/infra
docker compose --env-file ../.env stop          # stop containers, keep data
docker compose --env-file ../.env up -d         # start them again
```

**After a VM reboot,** wait two to three minutes, because Elasticsearch and Keycloak are slow to start, then check `docker ps` and `tail logs/cron.log`.

**A new shell session** needs the environment again:

```bash
cd ~/identityops-lab && source .venv/bin/activate
set -a; . ./.env; set +a
source kc_token.sh        # only when you want the token helper
```

**Reports.** Run `python -W ignore provisioning/snapshot.py` first, then any file in `reports/` with `mysql -h127.0.0.1 -ujml hr -t < reports/<file>.sql` (with `MYSQL_PWD` exported).

| Report | Shows |
|---|---|
| `01_leavers_with_access.sql` | Terminated employees who still have an enabled AD account |
| `02_orphaned_accounts.sql` | AD accounts with no matching HR record |
| `03_dormant_accounts.sql` | Enabled accounts with no logon for 90+ days (or never) |
| `04_manager_access_review.sql` | Which roles each active employee holds, grouped by manager |

## 12. Configuration reference

**Role model, `provisioning/roles.yaml`.** The `roles` section defines each role, its AD group (`ROLE-<name>`) and the entitlements it grants. The `assignments` section maps job titles to roles, and `baseline` roles go to everyone. To add a role, add it under `roles`, then map one or more job titles to it. The engine creates the AD group on its next run.

**HR data, `hr-source/schema.sql`.** The `employees` table is the source of truth. Key columns are `employee_id` (stored in AD as `employeeID`), names, `department`, `job_title`, `manager`, `status` (`active` or `terminated`) and the start and end dates. The `ad_accounts` and `ad_memberships` tables are filled by `snapshot.py` and are only used for reporting.

**Engine behaviour, `provisioning/jml.py`:**

- **Joiner:** creates the user in `OU=Users,OU=Corp` with a forced password change, then adds the role groups.
- **Mover:** compares current `ROLE-*` memberships with the desired ones for the job title, then adds and removes the difference. It only touches `ROLE-*` groups.
- **Leaver:** disables the account, removes all `ROLE-*` groups, and moves it to `OU=Disabled,OU=Corp`.
- **Logging:** every action is appended as one JSON line to `logs/provisioning.jsonl`. Failures are logged as `event: error` with a `kind`, and the run continues with the next employee.

**Log shipping, `monitoring/filebeat.yml`.** Filebeat reads `logs/*.jsonl` and writes to indices named `identityops-<date>`. Template management is switched off (`setup.template.enabled: false`) because Elasticsearch's default field mappings treat `event` as an object, while the engine logs it as a string. With the template on, every event is rejected.

## 13. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `Connection refused` to MySQL in `cron.log` right after a boot | MySQL was still starting. `run.sh` now waits for it, but run `docker ps` to confirm the container is up |
| `mysql` says "Lost connection ... reading initial communication packet" on first start | MySQL is still initialising. Wait 30 to 60 seconds |
| `Access denied for user 'jml'` | `DB_PASS` differs from the one used when the MySQL volume was first created. Reset with `docker compose ... down -v` and start again |
| Elasticsearch count stays at 0 and Filebeat logs `Cannot index event (status=400)` | Template conflict, see the Filebeat note above. Make sure `setup.template.enabled: false` is set, delete the old data streams and template, then recreate the Filebeat container so it re-reads the log |
| Elasticsearch exits at startup | Check `sysctl vm.max_map_count` (should be 262144) and free RAM |
| Kibana says the index pattern matches nothing | No documents yet. Fix ingestion first, then create the data view |
| Samba or Kerberos errors | Check the clock (`timedatectl`), that `/etc/resolv.conf` points to the VM, and `systemctl status samba-ad-dc` |
| Keycloak "Test connection" fails | Confirm `ldap server require strong auth = no`, that the bind DN is correct, and that port 389 is reachable from the container |
| Keycloak login "Invalid user credentials" for a valid AD user | You are on the master realm login. Use `/realms/lab/account`. For new accounts, reset the password first (they have a forced change) and sync users |
| Keycloak "Account is not fully set up" | The email attribute is still required. Turn it off in the realm's User profile |
| `kc_token: command not found` | Run `source kc_token.sh` in the current shell |
| A leaver can still sign in right after termination | Tokens and sessions issued before the termination stay valid until they expire (see section 15, Known lab shortcuts) |
| Engine reports `entryAlreadyExists` for a new hire | Another employee produces the same username or common name. Rename in HR |

## 14. Optional: failure test

Shows how an outage appears in the logs and on the dashboard, and how the engine recovers. Run it from `~/identityops-lab` with the environment loaded (see section 11).

```bash
sudo systemctl stop samba-ad-dc
python -W ignore provisioning/jml.py
jq -c 'select(.event=="error")' logs/provisioning.jsonl | tail -1   # kind: connection
```

The error count on the dashboard goes up within about 30 seconds. Then restore and confirm recovery:

```bash
sudo systemctl start samba-ad-dc
python -W ignore provisioning/jml.py && tail -1 logs/provisioning.jsonl   # run_complete
```

Cron also runs the engine every five minutes, so more error events may appear while Samba is stopped.

## 15. Known lab shortcuts

This is a lab, and these choices keep it simple. Each one needs a different answer in production.

- **Samba AD instead of Windows Server.** It is AD-compatible over LDAP and Kerberos, but it isn't Windows Server (no group policy, for example). The engine only uses LDAP, so it would work against a Windows Server domain with a connection change.
- **Plain LDAP between Keycloak and AD.** `ldap server require strong auth = no` allows unencrypted simple binds. Production would use LDAPS or StartTLS with a trusted certificate.
- **No TLS certificate validation in the engine.** It connects over LDAPS but accepts Samba's self-signed certificate. Production would validate against a trusted CA.
- **Over-privileged service account.** `svc-jml` is a Domain Admin. Production would delegate only the rights needed on the target OUs.
- **Security features turned off or relaxed.** Elasticsearch and Kibana run without authentication, and Keycloak runs in dev mode over HTTP with its built-in database. Kibana and Keycloak are reachable from the local network.
- **Shared initial password.** New accounts get the same initial password with a forced change at first logon. Production would use per-user random passwords delivered securely.
- **Simplistic account naming.** Usernames are first initial plus surname, so two people with the same name would collide (the engine reports the error and carries on). There is no rehire handling for a terminated employee who returns.
- **Tokens outlive termination.** Access tokens and SSO sessions issued before a termination stay valid until they expire. Production would use short token lifetimes and session revocation.
- **Polling instead of events.** The engine runs every five minutes from cron, so changes take up to five minutes to apply.
- **Single-node everything.** One domain controller and one VM, with no backups, high availability or secrets manager. Secrets live in a local `.env` file that is not committed.
- **Email requirement relaxed.** The engine doesn't set a mail attribute, so the Keycloak user profile doesn't require one.
- **No automated alerting.** Errors show on the Kibana dashboard, but nothing notifies anyone or opens a ticket.

## 16. Possible extensions

- Delegate least-privilege rights to `svc-jml` and document exactly which are needed
- LDAPS everywhere with a proper certificate chain
- A PowerShell version of the engine, or a Windows Server AD alongside Samba
- Entra ID sync with a Microsoft 365 developer tenant
- Segregation-of-duties analysis (a graph database is a good fit) and ticketing for failures
- A manager access-review workflow built on `reports/04_manager_access_review.sql`
