-- Orphaned accounts: in AD, but not in HR
SELECT a.sam, a.enabled, a.last_logon
FROM ad_accounts a LEFT JOIN employees e ON e.employee_id = a.employee_id
WHERE e.employee_id IS NULL;
