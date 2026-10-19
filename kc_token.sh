# Usage: export DEMO_PASS='...'; kc_token <username>
# The password is read from $DEMO_PASS (or a hidden prompt) and sent to curl on
# stdin, so it never appears in shell history or in curl's process arguments.
kc_token() {
  local user="$1" pass="${DEMO_PASS:-}"
  if [ -z "$pass" ]; then read -rsp "Password for $user: " pass; echo; fi
  printf '%s' "$pass" | curl -s -d 'client_id=demo-app' -d 'grant_type=password' \
      --data-urlencode "username=$user" --data-urlencode 'password@-' \
      http://localhost:8080/realms/lab/protocol/openid-connect/token \
  | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
if 'access_token' not in d:
    print('LOGIN FAILED:', d.get('error_description', d)); sys.exit()
t = d['access_token'].split('.')[1]
c = json.loads(base64.urlsafe_b64decode(t + '=' * (-len(t) % 4)))
print(json.dumps({k: c.get(k) for k in ('preferred_username', 'groups')}))"
}
