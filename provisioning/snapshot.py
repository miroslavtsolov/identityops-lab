import datetime
from jml import ad, hr_db, CORP

def main():
    conn, db, now = ad(), hr_db(), datetime.datetime.utcnow()
    conn.search(CORP, "(&(objectClass=user)(objectCategory=person))", paged_size=500,
                attributes=["sAMAccountName", "employeeID", "userAccountControl", "lastLogon", "memberOf"])
    with db.cursor() as c:
        c.execute("DELETE FROM ad_memberships")
        c.execute("DELETE FROM ad_accounts")
        for e in conn.entries:
            if "OU=ServiceAccounts" in e.entry_dn:
                continue
            ll = e.lastLogon.value
            ll = ll.replace(tzinfo=None) if isinstance(ll, datetime.datetime) and ll.year > 1970 else None
            enabled = 0 if int(e.userAccountControl.value) & 2 else 1
            emp = int(e.employeeID.value) if e.employeeID.value else None
            sam = str(e.sAMAccountName)
            c.execute("INSERT INTO ad_accounts VALUES (%s,%s,%s,%s,%s)", (sam, emp, enabled, ll, now))
            for g in e.memberOf.values:
                if g.upper().startswith("CN=ROLE-"):
                    c.execute("INSERT INTO ad_memberships VALUES (%s,%s)", (sam, g.split(",")[0][3:]))

if __name__ == "__main__":
    main()
