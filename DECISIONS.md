# Engineering Decisions

1. **Indexes.** Unique `emp_code` protects employee identity; unique `(emp_code, date)` prevents duplicate daily attendance. Compound employee/date and date/employee indexes support employee-month queries, punch operations, and paginated attendance. Department/join-date indexes support headcount and department filters. I avoided speculative indexes for every filter combination because indexes increase write and storage cost; explain plans should guide additions.

2. **Punch-in race.** Concurrent requests may both reach the insert, but the unique `(emp_code, date)` index permits only one document. The winner returns `201`; MongoDB rejects the other insert with a duplicate-key error, mapped to `409`. A pre-insert check is not the correctness boundary.

3. **Ties.** `$rank` gives equal totals the same rank and skips the next rank. The limit is applied after ranking, so all rows tied at a rank within the limit are returned, ordered by employee code.

4. **Headcount.** The summary starts from employees who joined by the month's end and left-joins attendance logs. Employees with no logs remain and count once; employees joining later are excluded.

5. **100x scale.** I would benchmark real plans and latency, then consider daily summary tables, scheduled rollups, and a separate analytics workload. I would not add caching or denormalization before measuring the bottleneck.
