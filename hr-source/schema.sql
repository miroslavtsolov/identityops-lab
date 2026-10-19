CREATE TABLE employees (
  employee_id INT PRIMARY KEY,
  first_name VARCHAR(50) NOT NULL,
  last_name  VARCHAR(50) NOT NULL,
  department VARCHAR(50) NOT NULL,
  job_title  VARCHAR(80) NOT NULL,
  manager    VARCHAR(100),
  status ENUM('active','terminated') NOT NULL DEFAULT 'active',
  start_date DATE,
  end_date DATE NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE ad_accounts (
  sam VARCHAR(64) PRIMARY KEY,
  employee_id INT NULL,
  enabled TINYINT NOT NULL,
  last_logon DATETIME NULL,
  snapshot_at DATETIME NOT NULL
);

CREATE TABLE ad_memberships (
  sam VARCHAR(64) NOT NULL,
  group_name VARCHAR(100) NOT NULL
);

INSERT INTO employees (employee_id, first_name, last_name, department, job_title, manager, start_date) VALUES
 (1001,'Anna','Petrova','Finance','Finance Analyst','Ivan Georgiev','2024-03-01'),
 (1002,'Ivan','Georgiev','Finance','Finance Manager','CFO Office','2021-06-15'),
 (1003,'Maria','Ilieva','IT','IT Support Engineer','Dimitar Kolev','2023-09-01'),
 (1004,'Dimitar','Kolev','IT','IT Manager','CIO Office','2020-01-10'),
 (1005,'Georgi','Stoyanov','HR','HR Partner','CHRO Office','2022-11-01'),
 (1006,'Elena','Marinova','Finance','Finance Analyst','Ivan Georgiev','2025-02-03');
