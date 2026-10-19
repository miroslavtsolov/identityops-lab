-- Dormant accounts: enabled, no logon for 90+ days (never logged on counts too)
SELECT sam, last_logon FROM ad_accounts
WHERE enabled = 1 AND (last_logon IS NULL OR last_logon < NOW() - INTERVAL 90 DAY);
