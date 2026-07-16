# Project Atlas

Project Atlas is a local SEO publishing platform foundation for service businesses. Version 0.12 adds a QA remediation workspace, manual review notes, approval audit snapshots, and a separate media backup download.

The initial seeded business is Flo-Zone Pest And Termite Solutions Inc, but the app structure is business-agnostic so future companies and industries can be added without changing core code.

## Project Atlas Command Center

Project Atlas is a local SEO and service-business publishing platform for Flo-Zone Pest And Termite Solutions Inc, starting with drywood termite tenting city pages.

### Current local URLs

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Generated Pages: http://localhost:5173/generated-pages
- Approval Queue: http://localhost:5173/approval-queue

WordPress Sandbox, Draft Queue, Draft Review, and Export Package tools are also part of the platform.

### Current verified version

- Latest checkpoint: v0.59.51
- Backend tests verified: 541 passed, 1 intentional platform-specific skip
- Frontend build verified
- Machine setup hardened
- Restore drill documented

### Protected paths

Never delete, move, rename, clean up, overwrite, or modify these paths unless Shawn explicitly asks:

- backend/backups
- backend/media
- frontend/public/media

See:

- docs/PROTECTED_PATHS.md
- docs/BACKUP_AND_RESTORE.md

### Required backups before major work

Before major build steps, run all three Atlas backups:

- Data Backup JSON
- Media Backup ZIP
- Program Backup ZIP

### Start Atlas

From the project root:

docker compose up -d

### Check running containers

docker ps

Expected containers:

- atlas_frontend
- atlas_backend
- atlas_postgres

### Verify frontend inside Docker

docker exec -it atlas_frontend npm run build

### Verify frontend on Windows

cd frontend
npm install
npm run build
cd ..

### Verify backend tests

docker exec atlas_backend sh -lc "PYTHONPATH=/app pytest"

Expected backend result as of v0.59.51:

541 passed, 1 intentional platform-specific skip

### Git safety check

git status

Safe result:

nothing to commit, working tree clean

### Version checkpoint process

For each major version:

1. Run backups.
2. Verify current app works.
3. Make one controlled improvement.
4. Run frontend build.
5. Run backend tests.
6. Commit.
7. Tag the version.
8. Push commit and tag.
9. Confirm git status is clean.

### Important docs

- docs/NEW_COMPUTER_SETUP.md
- docs/BACKUP_AND_RESTORE.md
- docs/PROTECTED_PATHS.md
- docs/VERSION_HISTORY.md
- docs/RESTORE_DRILL.md
- docs/MACHINE_SETUP.md

## Stack

- Backend: Python FastAPI
- ORM: SQLModel / SQLAlchemy
- Frontend: React with TypeScript
- Database: PostgreSQL
- Local development: Docker Compose

## Project Structure

```text
backend/
  app/
    api/
    core/
    db/
    models/
    schemas/
    services/
  alembic/
  backups/
frontend/
  src/
docker-compose.yml
```

## Run Locally With Docker

1. Copy the environment files:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

2. Start the app:

```bash
docker compose up --build
```

3. Open:

- Frontend dashboard: http://localhost:5173
- Backend API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Seed Data

The backend seeds Flo-Zone Pest And Termite Solutions Inc automatically on startup when `SEED_ON_STARTUP=true`.

To run the seed manually:

```bash
docker compose exec backend python -m app.db.seed
```

Seeded records include:

- Flo-Zone business profile
- Drywood termite tenting service
- Orange, Seminole, Volusia, Lake, and Flagler Counties
- 55 incorporated cities, towns, and villages across the target counties
- City priority fields, with Orlando marked as the primary market
- Draft city-service generated pages for drywood termite tenting
- 18 drywood termite and fumigation Service Knowledge Blocks
- Starter image metadata record

The seed script is idempotent. It updates known Flo-Zone records, target cities, queued pages, and knowledge blocks without creating duplicates.

## Backup And Restore

Atlas JSON backups protect businesses, services, counties, cities, generated pages, image metadata, settings, and knowledge blocks. Each backup includes a version label, creation timestamp, and count for every exported table.

Create a backup:

```bash
docker compose exec backend python -m app.db.backup export
```

Backup files use names such as `atlas-backup-2026-06-29-193000.json` and are stored in `backend/backups` on the host. The Backups screen at `http://localhost:5173/backups` can also create backups and show their metadata and table counts.

The Backups screen can separately download a media ZIP named like `atlas-media-backup-2026-07-01-120000.zip`. It contains only `backend/media` and `frontend/public/media`, preserving those paths inside the archive. Media ZIPs are generated in memory and downloaded by the browser; they are not stored in or restored from `backend/backups`.

Restore a backup with conservative, non-destructive upserts:

```bash
docker compose exec backend python -m app.db.backup restore backend/backups/<filename>.json
```

Restore is CLI-only in v0.4. It validates the backup structure, counts, stable keys, and relationships before committing. It updates matching records and adds missing records without deleting other database data. Invalid or inconsistent backups fail and roll back.

Backup files may contain business data, generated content, contact details, and internal notes. Store them securely. After export, copy the JSON file from `backend/backups` to a protected OneDrive, Google Drive, Dropbox, or external-drive folder. Keep access to that storage restricted and follow its encryption and retention options.

Create and copy a fresh backup before major Atlas updates, migrations, bulk imports, or content-generation runs. Periodically test that an archived backup can be read and listed.

## AI Draft Page Generator

Atlas v0.5 generates structured city-service drafts from the existing business, service, city, county, settings, and active Knowledge Block records. Generated content remains in Atlas with page status `draft`; nothing is published to WordPress.

The default provider is `mock`. It creates deterministic, realistic drafts without an external AI API key. Provider selection is configured with:

```text
AI_PROVIDER=mock
AI_API_KEY=
```

Each generated draft stores:

- Title, meta title, meta description, and H1
- Introduction and treatment context
- Signs, process, and preparation sections
- Realtor and property-manager guidance
- FAQs and call to action
- Internal review notes
- Generation status and timestamp

The generator rejects unsafe absolute claims including `100% guaranteed`, `always eliminates`, `permanent protection`, `safe for everyone`, `no risk`, `harmless`, and unsupported `pesticide-free` claims.

Open `http://localhost:5173/generated-pages` to:

- Filter the queue by county, city, or page status
- Preview a batch without changing the database
- Generate eligible draft pages after preview
- Generate or refresh one draft page
- Review structured fields before marking a draft approved

Batch generation only updates pages whose current status is `draft`. Approved and published pages are skipped. Single-page generation also blocks non-draft pages unless an API caller explicitly supplies overwrite confirmation.

Generation API routes:

- `POST /api/generated-pages/{id}/generate-draft`
- `POST /api/generated-pages/generate-batch-preview`
- `POST /api/generated-pages/generate-batch`

## Page Preview Template

Generated pages with structured draft content include a `Preview Page` action. The standalone route `/generated-pages/{id}/preview` renders the existing draft as a responsive Flo-Zone service page with placeholder media areas, customer calls to action, FAQs, license information, and a clear draft/not-published review banner.

Preview mode is read-only. It does not publish content, connect to WordPress, call external APIs, or change the generated page record.

## Preview Media Assignment

Image Metadata records can store an asset URL, city/service-friendly title, reviewed alt text, review status, city, county, service, and intended image role. Generated pages can assign one reviewed image to each supported role:

- `hero`
- `service`
- `support`

Select a page on the Generated Pages screen to assign, change, or remove preview media. Only reviewed, compatible images with an asset URL and reviewed alt text are eligible. Media assignment never changes draft content or approval status.

The page preview renders assigned hero and service images responsively and retains the existing placeholder when a role is unassigned.

Media API routes:

- `GET /api/generated-pages/{id}/media`
- `PUT /api/generated-pages/{id}/media/{role}`
- `DELETE /api/generated-pages/{id}/media/{role}`

## Media Upload And Optimization

Open `http://localhost:5173/image-metadata` to upload JPEG, PNG, or WebP files into the Media Library. Atlas stores the original under `backend/media/originals`, generates a bounded web-friendly derivative and thumbnail, and creates an Image Metadata record with `pending_review` status.

Upload controls accept a maximum of 10 MB by default and reject unsupported or invalid image content. Limits and the public media URL are configurable:

```text
MEDIA_ROOT=media
MEDIA_PUBLIC_URL=http://localhost:8000/media
MEDIA_MAX_UPLOAD_BYTES=10485760
MEDIA_MAX_PIXELS=40000000
```

Before assignment, use the review editor to add a descriptive title and reviewed alt text, confirm the city, county, service, and intended role, then mark the image `reviewed`. Pending images remain visible in the library but cannot be assigned to generated pages.

Upload API:

- `POST /api/media/upload`

Removing a page assignment removes only the database link. It does not delete any managed image file. Uploading or reviewing media does not modify generated page content, status, or approval state.

JSON backups include all media metadata and page assignments. Managed image binaries remain in `backend/media`; back up that folder alongside the JSON files when copying Atlas backups to external storage.

## Focal Points And Responsive Crops

Every image stores normalized `focal_x` and `focal_y` values between `0` and `1`. New and existing images default to the center point at `0.5, 0.5`.

Open an image in the Media Library review editor to:

- Adjust horizontal and vertical focal sliders
- Click directly on a crop preview to move the focal point
- Compare `hero_desktop`, `hero_mobile`, `card_thumbnail`, `square`, and `original` display presets
- Save focal metadata without modifying the original or optimized image files

Customer-facing page previews prefer the optimized image URL when available and apply the saved focal point with responsive `object-position` styling. Assigned images retain reviewed alt text, and unassigned roles continue to use placeholders.

Crop presets are non-destructive display previews in v0.9. Atlas does not create separate destructive crop files.

## Page Media Overrides And Galleries

Generated pages can reuse reviewed media without changing the global image record. Each page assignment supports:

- Optional page-specific focal X/Y overrides
- Optional page-specific alt text
- A display preset
- Sort order

When focal or alt overrides are empty, previews fall back to the reviewed image metadata. Hero assignments remain singular per page. Service and support roles accept multiple unique images and render in their saved order.

The Generated Pages media panel groups all assignments by role. It can replace the hero, add service/support images, reorder gallery items, edit or clear page focal overrides, edit page alt text, select display presets, and remove only the assignment link.

Assignment API routes:

- `GET /api/generated-pages/{id}/media`
- `POST /api/generated-pages/{id}/media`
- `PATCH /api/generated-pages/{id}/media/assignments/{assignment_id}`
- `DELETE /api/generated-pages/{id}/media/assignments/{assignment_id}`
- `PUT /api/generated-pages/{id}/media/order/{role}`

Removing an assignment never deletes Image Metadata or image files. Page media changes do not modify generated draft JSON, page status, or publication state.

## Content And Media QA

Each generated page can be evaluated without publishing or approving it. The deterministic QA checklist verifies required structured content, local city/service context, business contact and license information, safe wording, placeholder copy, reviewed media, hero alt text, and preview availability.

Readiness statuses:

- `ready`: every blocker and warning check passes
- `needs_review`: no blockers, but one or more warning checks need attention
- `blocked`: one or more blocker checks fail

Single-page QA and batch preview/run controls are available on the Generated Pages screen. Batch preview is read-only. Batch run stores only the latest QA status, checklist JSON, and check timestamp; it does not modify generated draft content, page status, or the page content timestamp.

Approval is explicit and gated. The Approve button remains disabled until a saved `ready` result exists, and the backend reruns QA before accepting approval.

Failed and warning checks include a suggested fix and likely issue location. The Generated Pages screen can filter by readiness, warnings, blockers, or QA-not-run status and shows an issue-only remediation workspace. Guidance is informational; Atlas never rewrites draft content automatically.

Manual page review notes, reviewer text, and review timestamps are stored separately from generated draft JSON. Successful approval creates an immutable audit record containing the reviewer, QA snapshot, QA timestamp, canonical draft hash, and page status transition. Blocked approvals do not create audit records.

QA API routes:

- `GET /api/generated-pages/{id}/qa`
- `POST /api/generated-pages/{id}/qa/run`
- `POST /api/generated-pages/qa/batch-preview`
- `POST /api/generated-pages/qa/batch-run`
- `PATCH /api/generated-pages/{id}/review`
- `GET /api/generated-pages/{id}/approval-history`
- `GET /api/generated-pages/approval-history-summary`
- `POST /api/generated-pages/{id}/approve`

Atlas preview links may add `?qa=1` to display an internal QA banner. The ordinary preview route does not render QA information.

## Service Knowledge Blocks

Knowledge Blocks store reviewed, reusable service facts before AI page generation is enabled. Each block belongs to a business and service and records a question, short and long answers, category, customer type, confidence level, source notes, ordering, and publication status.

The v0.3 seed adds 18 blocks covering:

- Drywood termite and tenting basics
- Preparation, safety, and re-entry
- Vikane facts and warning-agent guidance
- Realtors, commercial clients, and property managers
- Identification signs and treatment limitations
- Multi-story boom-lift access

Run the normal seed command to create or refresh them:

```bash
docker compose exec backend python -m app.db.seed
```

Open `http://localhost:5173/knowledge-blocks` to filter the library and edit answers, confidence levels, or source notes. The REST CRUD endpoint is `http://localhost:8000/api/knowledge-blocks`.

These blocks are the reviewed knowledge foundation for a later AI page-generation phase. Version 0.3 does not generate page content or send content to WordPress.

## Page Queue

The drywood termite tenting city-page queue can be run independently:

```bash
docker compose exec backend python -m app.db.queue_pages
```

The queue creates or updates one `city_service` draft page per city for the drywood termite tenting service.

Expected page format:

- Slug: `drywood-termite-tenting-{city-slug}-fl`
- Page title: `Drywood Termite Tenting in {City}, FL`
- H1: `Drywood Termite Tenting in {City}, Florida`
- Status: `draft`

Running the queue more than once is safe and should not create duplicates.

## Verify Counts

After startup or after running the seed script:

- Target counties: 5
- Target cities: 55
- Drywood termite tenting city-service draft pages: 55
- Drywood termite tenting knowledge blocks: 18

Quick API checks:

```bash
curl http://localhost:8000/api/counties
curl http://localhost:8000/api/cities
curl http://localhost:8000/api/generated-pages
curl http://localhost:8000/api/knowledge-blocks
```

In the browser:

- Cities screen: filter by county or priority and confirm Orlando is `Primary` and marked as a primary market.
- Generated Pages screen: filter by county, city, or status and confirm `55 city-service pages`.
- Generated Pages screen: preview a filtered batch, generate one draft, review every structured field, and confirm approved rows cannot be regenerated.
- Knowledge Blocks screen: confirm `18` records, test all three filters, and edit a block's answers or source notes.
- Backups screen: create a backup and confirm its file name, timestamp, status, and expected table counts.

## Backend Development

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set `DATABASE_URL` in `backend/.env` before running locally outside Docker.

## Frontend Development

```bash
cd frontend
npm install
npm run dev
```

## API Modules

- `/api/businesses`
- `/api/services`
- `/api/counties`
- `/api/cities`
- `/api/generated-pages`
- `/api/generated-pages/{id}/generate-draft`
- `/api/generated-pages/generate-batch-preview`
- `/api/generated-pages/generate-batch`
- `/api/generated-pages/{id}/qa`
- `/api/generated-pages/qa/batch-preview`
- `/api/generated-pages/qa/batch-run`
- `/api/image-metadata`
- `/api/media/upload`
- `/api/knowledge-blocks`
- `/api/backups`
- `/api/backups/export`
- `/api/settings`

Data modules support basic create, read, update, and delete operations. Backup restore remains CLI-only.

## Tests

Backend tests cover city/page seeding, Knowledge Blocks, backup/restore, media upload and optimization, media assignment safety, prompt assembly, safe-wording enforcement, deterministic draft generation, protected-page behavior, and batch preview/generation:

```bash
cd backend
pytest
```

For an existing Docker installation, restart and rebuild with:

```bash
docker compose down
docker compose up --build -d
docker compose exec backend python -m app.db.seed
```

The app applies additive schema guards during startup. Alembic migrations are included through `backend/alembic/versions/20260701_0010_qa_remediation_approval_audits.py`.
