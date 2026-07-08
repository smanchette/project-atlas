\# Project Atlas Protected Paths



These paths are protected and must never be deleted, moved, renamed, cleaned up, overwritten, or modified unless Shawn explicitly asks for it.



\## Protected paths



backend/backups

backend/media

frontend/public/media



\## Rules



1\. Do not run cleanup scripts against these folders.

2\. Do not include these folders in reset, rebuild, or delete commands.

3\. Do not rename these folders.

4\. Do not move media files unless there is a specific written migration plan.

5\. Before any major version change, run all three Atlas backups:

&#x20;  - Data Backup JSON

&#x20;  - Media Backup ZIP

&#x20;  - Program Backup ZIP



\## Reason



These folders may contain business data, customer-ready assets, generated media, and recovery files. Losing them can damage the platform.

