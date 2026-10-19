-- Leavers who still have an enabled account (critical finding)
SELECT e.employee_id, e.first_name, e.last_name, e.end_date, a.sam
FROM employees e JOIN ad_accounts a ON a.employee_id = e.employee_id
WHERE e.status = 'terminated' AND a.enabled = 1;
