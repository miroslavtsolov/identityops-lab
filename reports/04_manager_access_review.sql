-- Manager access review: who has which role, grouped by manager
SELECT e.manager, CONCAT(e.first_name,' ',e.last_name) AS employee, e.job_title, m.group_name
FROM employees e
JOIN ad_accounts a ON a.employee_id = e.employee_id
JOIN ad_memberships m ON m.sam = a.sam
WHERE e.status = 'active'
ORDER BY e.manager, employee, m.group_name;
