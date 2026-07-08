\# Project Atlas Backup and Restore



Project Atlas uses three backup types before major work.



\## Required backups before major steps



Run all three:



\- Data Backup JSON

\- Media Backup ZIP

\- Program Backup ZIP



\## What each backup protects



\### Data Backup JSON



Protects platform data such as generated pages, approvals, notes, revision history, WordPress draft records, and related database-driven content.



\### Media Backup ZIP



Protects uploaded and generated media files.



Protected media locations include:



\- backend/media

\- frontend/public/media



\### Program Backup ZIP



Protects the working program files so the current app state can be recovered if a code change breaks the platform.



\## Protected folders



Never delete, move, rename, clean up, or modify these folders unless Shawn explicitly asks:



\- backend/backups

\- backend/media

\- frontend/public/media



\## Restore principle



Restore order should be:



1\. Restore the program/project files.

2\. Restore media folders.

3\. Restore data backup.

4\. Start Docker.

5\. Confirm frontend and backend load.

6\. Run verification checks.



\## Verification after restore



Frontend:



docker exec -it atlas\_frontend npm run build



Backend:



docker exec -it atlas\_backend sh -lc "PYTHONPATH=/app pytest"



Expected backend result as of v0.13:



119 passed

