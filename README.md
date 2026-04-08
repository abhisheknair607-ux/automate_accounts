# Invoice Reconciliation MVP

Production-oriented MVP for reconciling supplier invoices against delivery dockets for a large retailer.

The app ingests:

- supplier invoice PDFs
- delivery docket images or PDFs
- an accounting template image/file

It then:

- stores raw documents locally
- runs OCR/document extraction through a pluggable provider interface
- normalizes results into a canonical schema
- reconciles invoice vs delivery docket with configurable tolerances
- flags mismatches and low-confidence fields into an exception workflow
- exports approved data as CSV or JSON in the accounting-template structure

## Project Structure

```text
.
├── backend
│   ├── alembic
│   ├── app
│   │   ├── api
│   │   ├── core
│   │   ├── db
│   │   ├── sample_data/fixtures
│   │   ├── schemas
│   │   ├── scripts
│   │   ├── services
│   │   └── tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend
│   ├── app
│   ├── components
│   ├── lib
│   └── Dockerfile
├── Accounting Template.png
├── Delivery Docket.jpeg
├── Invoice_598527_Account_64876_Division_MRPI_Full_unlocked.pdf
├── docker-compose.yml
└── .env.example
```

## Backend Highlights

- `FastAPI` API with upload, extract, reconcile, review, and export endpoints
- `SQLAlchemy` models for `documents`, `extraction_runs`, `invoices`, `invoice_lines`, `delivery_dockets`, `delivery_lines`, `reconciliation_runs`, `reconciliation_issues`, and `exports`
- `Alembic` initial migration
- pluggable extraction provider interface
- `mock` provider backed by realistic JSON fixtures from the supplied sample docs
- `tesseract` provider for local OCR through an installed Tesseract binary
- `ocr_space` provider for a free trial OCR flow using OCR.space
- `google_document_ai` provider for Google Cloud Document AI processors
- `azure_document_intelligence` provider for live Azure OCR/document extraction
- configurable reconciliation tolerances and reason codes
- local file storage abstraction that can be swapped for S3 later

## Frontend Highlights

- `Next.js + TypeScript` review console
- upload page
- case overview with extraction, reconciliation, and export actions
- invoice view
- delivery docket view
- reconciliation results view
- exception review view
- exports view

## Canonical Schema

Pydantic models are defined in [backend/app/schemas/canonical.py](/c:/Users/itsab/OneDrive/Desktop/Projects/Automate/backend/app/schemas/canonical.py) and cover:

- `Supplier`
- `Store`
- `InvoiceHeader`
- `InvoiceLine`
- `TaxSummary`
- `DiscountSummary`
- `DeliveryDocket`
- `DeliveryLine`
- `ReconciliationResult`
- `AccountingExportRow`
- `ExceptionCase`

## Sample Fixtures

The repo includes mock extraction fixtures under [backend/app/sample_data/fixtures](/c:/Users/itsab/OneDrive/Desktop/Projects/Automate/backend/app/sample_data/fixtures).

Important:

- the invoice anchors match the supplied sample details:
  `invoice_number=598527`, `invoice_date=2026-03-24`, `account_number=64876`, `store_number=2064`, `supplier=Musgrave Retail / Musgrave Retail Partners Ireland`
- line items, docket values, and template column definitions are realistic mock fixtures where OCR from the supplied scanned documents was uncertain
- all uncertain areas are explicitly marked with `mock_data=true`, `notes`, and `low_confidence_fields`

## Local Run

### 1. Backend

Local backend runs use SQLite by default so you can bring the UI up quickly on your PC without provisioning Postgres first. Docker still uses PostgreSQL.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

If you want PostgreSQL locally instead of the default SQLite file, set `DATABASE_URL` in `.env`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend URL: `http://localhost:3000`

Backend URL: `http://localhost:8000`

API docs: `http://localhost:8000/docs`

### Local OCR With Tesseract

If you want local OCR without an external API:

1. Install Tesseract OCR on your machine.
2. Copy `.env.example` to `.env`
3. Set:
   `DEFAULT_EXTRACTION_PROVIDER=tesseract`
   `TESSERACT_COMMAND=tesseract`
4. If Tesseract is not on your `PATH`, point `TESSERACT_COMMAND` at the full executable path.
5. Restart the backend

The backend uses the same preprocessing and fallback heuristics as the OCR.space flow, but the OCR call runs locally through the Tesseract CLI instead of an HTTP API.

### Free Trial OCR With OCR.space

If you want a free live OCR demo without Azure:

1. Copy `.env.example` to `.env`
2. Set:
   `DEFAULT_EXTRACTION_PROVIDER=ocr_space`
   `OCR_SPACE_API_KEY=helloworld`
3. Restart the backend

`helloworld` is OCR.space's shared demo key, so it is fine for a trial but can be throttled. For anything beyond a quick demo, create your own free OCR.space key and replace it.

The backend preprocesses large images, rotates landscape scans when OCR quality is clearly better after rotation, and only renders the first plus last invoice PDF pages by default so the sample invoice stays lightweight on free OCR limits.

### Google Document AI

If you want Google Cloud OCR and parsing:

1. Enable Document AI in your Google Cloud project and create processors.
2. Set up Application Default Credentials locally.
3. Copy `.env.example` to `.env`
4. Set:
   `DEFAULT_EXTRACTION_PROVIDER=google_document_ai`
   `GOOGLE_DOCUMENT_AI_PROJECT_ID=your-gcp-project-id`
   `GOOGLE_DOCUMENT_AI_LOCATION=us`
   `GOOGLE_DOCUMENT_AI_INVOICE_PROCESSOR_ID=your-invoice-processor-id`
   `GOOGLE_DOCUMENT_AI_LAYOUT_PROCESSOR_ID=your-layout-processor-id`
5. Restart the backend

Use an Invoice processor for invoice PDFs and a Layout parser processor for delivery dockets and template-style documents. The provider uses Google ADC for auth, so `gcloud auth application-default login` or `GOOGLE_APPLICATION_CREDENTIALS` must already be configured in your shell environment.

### Azure Document Intelligence

If you want the UI extract button to use Azure instead of the mock fixtures:

1. Copy `.env.example` to `.env`
2. Set:
   `DEFAULT_EXTRACTION_PROVIDER=azure_document_intelligence`
   `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=...`
   `AZURE_DOCUMENT_INTELLIGENCE_KEY=...`
3. Restart the backend

The frontend now uses the backend default provider automatically, so you do not need to hardcode the provider in the UI.

## Fastest Way To View The Frontend On Your PC

1. Open one terminal:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

3. Open `http://localhost:3000`

4. Upload the three supplied sample files from the repo root:

- `Invoice_598527_Account_64876_Division_MRPI_Full_unlocked.pdf`
- `Delivery Docket.jpeg`
- `Accounting Template.png`

## Docker Run

```bash
copy .env.example .env
docker compose up --build
```

This starts:

- PostgreSQL on `localhost:5432`
- FastAPI on `localhost:8000`
- Next.js on `localhost:3000`

## Netlify Deploy

This repo is ready for a Netlify frontend deploy with the root [netlify.toml](/c:/Users/itsab/OneDrive/Desktop/Projects/Automate/netlify.toml).

Important:

- Netlify should deploy the `frontend` app only
- the `backend` FastAPI service still needs to be hosted separately
- set `NEXT_PUBLIC_API_BASE_URL` in Netlify to your deployed backend URL, for example:
  `https://your-backend-host.example.com/api`

Suggested Netlify setup:

1. Connect the repository in Netlify.
2. Let Netlify use the root `netlify.toml`.
3. Add environment variable:
   `NEXT_PUBLIC_API_BASE_URL=https://your-backend-host.example.com/api`
4. Deploy the site.

The included Netlify config uses:

- base directory: `frontend`
- build command: `npm run build`
- publish directory: `.next`
- Node.js version: `20`

## Seed The Supplied Sample Files

After the backend dependencies are installed:

```bash
cd backend
python -m app.scripts.seed_sample_case
```

That script:

- copies the three supplied sample files into backend storage
- creates a case
- runs extraction with the provider configured in `.env`
- runs reconciliation
- generates a CSV export

## Test Suite

```bash
python -m pytest backend/app/tests -q
```

Current test coverage includes:

- fixture validation against the canonical schema
- reconciliation rule unit tests
- API flow tests for upload -> extract -> reconcile -> export

## Main API Endpoints

- `POST /api/cases/uploads`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `POST /api/cases/{case_id}/extract`
- `GET /api/cases/{case_id}/invoice`
- `GET /api/cases/{case_id}/delivery-docket`
- `POST /api/cases/{case_id}/reconcile`
- `GET /api/cases/{case_id}/reconciliation`
- `GET /api/cases/{case_id}/exceptions`
- `POST /api/exports/cases/{case_id}`
- `GET /api/exports/{export_id}/download`

## Reconciliation Rules Implemented

- invoice number format validation
- supplier matching
- account number matching
- store number matching
- line matching by SKU or normalized description
- quantity comparison
- unit-price comparison
- line-amount comparison
- VAT total comparison
- grand-total comparison
- tolerance-based approval
- low-confidence extraction review flags
- mismatch reason codes

## OCR Provider Architecture

Provider interface:

- [backend/app/services/extraction/providers/base.py](/c:/Users/itsab/OneDrive/Desktop/Projects/Automate/backend/app/services/extraction/providers/base.py)

Mock provider:

- [backend/app/services/extraction/providers/mock_provider.py](/c:/Users/itsab/OneDrive/Desktop/Projects/Automate/backend/app/services/extraction/providers/mock_provider.py)

OCR.space provider:

- [backend/app/services/extraction/providers/ocr_space_provider.py](/c:/Users/itsab/OneDrive/Desktop/Projects/Automate/backend/app/services/extraction/providers/ocr_space_provider.py)

Azure provider:

- [backend/app/services/extraction/providers/azure_stub.py](/c:/Users/itsab/OneDrive/Desktop/Projects/Automate/backend/app/services/extraction/providers/azure_stub.py)

## Notes For Production Hardening

- tune the Azure field mapping with supplier-specific rules for your real document set
- move storage from local disk to S3-compatible object storage
- add authentication and RBAC for reviewers
- move long-running extraction/export work to Celery workers
- add richer exception resolution states and audit events
- add supplier-specific parsing rules and fuzzy master-data matching
- evolve the template parser from image-based mock config to real spreadsheet mapping
