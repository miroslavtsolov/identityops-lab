import os, json, ssl, datetime, yaml, pymysql
from ldap3 import Server, Connection, Tls, MODIFY_REPLACE, ALL

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "DC=lab,DC=internal"
CORP = f"OU=Corp,{BASE}"
USERS_OU, DISABLED_OU, GROUPS_OU = (f"OU={n},{CORP}" for n in ("Users", "Disabled", "Groups"))
LOG = os.path.join(HERE, "..", "logs", "provisioning.jsonl")
CFG = yaml.safe_load(open(os.path.join(HERE, "roles.yaml")))

def log(event, **kw):
    rec = {"@timestamp": datetime.datetime.utcnow().isoformat() + "Z", "event": event, **kw}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")

def ad():
    srv = Server(os.environ["AD_HOST"], port=636, use_ssl=True,
                 tls=Tls(validate=ssl.CERT_NONE), get_info=ALL)   # lab: self-signed cert
    return Connection(srv, user=os.environ["AD_BIND"], password=os.environ["AD_PASS"], auto_bind=True)

def hr_db():
    return pymysql.connect(host="127.0.0.1", user="jml", password=os.environ["DB_PASS"],
                           database="hr", cursorclass=pymysql.cursors.DictCursor, autocommit=True)

def desired_groups(emp):
    a = CFG["assignments"]
    roles = set(a["baseline"]) | set(a["by_title"].get(emp["job_title"], []))
    return {CFG["roles"][r]["group"] for r in roles}

def sam_name(emp):
    return (emp["first_name"][0] + emp["last_name"]).lower()

def find(conn, emp_id):
    conn.search(CORP, f"(employeeID={emp_id})", attributes=["userAccountControl", "memberOf"])
    return conn.entries[0] if conn.entries else None

def ensure_groups(conn):
    for r in CFG["roles"].values():
        conn.search(GROUPS_OU, f"(cn={r['group']})")
        if not conn.entries:
            conn.add(f"CN={r['group']},{GROUPS_OU}", ["top", "group"],
                     {"sAMAccountName": r["group"], "groupType": -2147483646})
            log("group_created", group=r["group"])

def create_user(conn, emp):
    s = sam_name(emp)
    dn = f"CN={emp['first_name']} {emp['last_name']},{USERS_OU}"
    ok = conn.add(dn, ["top", "person", "organizationalPerson", "user"], {
        "sAMAccountName": s, "userPrincipalName": f"{s}@lab.internal",
        "givenName": emp["first_name"], "sn": emp["last_name"],
        "displayName": f"{emp['first_name']} {emp['last_name']}",
        "employeeID": str(emp["employee_id"]),
        "department": emp["department"], "title": emp["job_title"]})
    if not ok:
        raise RuntimeError(f"create failed for {s}: {conn.result['description']}")
    conn.extend.microsoft.modify_password(dn, os.environ["TEMP_PASSWORD"])
    conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [512])],
                     "pwdLastSet": [(MODIFY_REPLACE, [0])]})   # must change at first logon
    log("user_created", employee_id=emp["employee_id"], account=s)
    return dn

def sync_groups(conn, dn, emp_id, want):
    conn.search(dn, "(objectClass=user)", search_scope="BASE", attributes=["memberOf"])
    have = {g.lower(): g for g in conn.entries[0].memberOf.values if g.upper().startswith("CN=ROLE-")}
    want_dns = {f"CN={g},{GROUPS_OU}".lower(): f"CN={g},{GROUPS_OU}" for g in want}
    for k, g in want_dns.items():
        if k not in have:
            conn.extend.microsoft.add_members_to_groups(dn, g)
            log("group_added", employee_id=emp_id, group=g.split(",")[0][3:])
    for k, g in have.items():
        if k not in want_dns:
            conn.extend.microsoft.remove_members_from_groups(dn, g)
            log("group_removed", employee_id=emp_id, group=g.split(",")[0][3:])

def disable_user(conn, entry, emp):
    dn = entry.entry_dn
    conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [514])]})
    sync_groups(conn, dn, emp["employee_id"], set())
    if not dn.upper().endswith(DISABLED_OU.upper()):
        conn.modify_dn(dn, dn.split(",")[0], new_superior=DISABLED_OU)
    log("user_disabled", employee_id=emp["employee_id"])

def fail(kind, emp_id, err):
    log("error", kind=kind, employee_id=emp_id, error=str(err), severity="high")

def run():
    try:
        conn = ad()
        ensure_groups(conn)
        with hr_db().cursor() as c:
            c.execute("SELECT * FROM employees")
            rows = c.fetchall()
    except Exception as e:
        fail("connection", None, e)
        return
    for emp in rows:
        try:
            entry = find(conn, emp["employee_id"])
            if emp["status"] == "terminated":
                if entry and not int(entry.userAccountControl.value) & 2:
                    disable_user(conn, entry, emp)
                continue
            dn = entry.entry_dn if entry else create_user(conn, emp)
            sync_groups(conn, dn, emp["employee_id"], desired_groups(emp))
        except Exception as e:
            fail("employee_sync", emp["employee_id"], e)
    log("run_complete", employees=len(rows))

if __name__ == "__main__":
    run()
