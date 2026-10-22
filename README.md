# MedMitra — Pharmacy Ordering & Inventory Management

MedMitra is a Django application focused on pharmacy operations: medicine catalogue and search, participating pharmacy listings, customer carts and medicine orders, prescription upload/review for prescription-required items, store order processing, and a pharmacy counter inventory/POS workspace.

> **Demo / college project:** This is not a certified online pharmacy platform. Before real sales, confirm current Indian licensing, prescription, privacy, consumer-protection, delivery, and payment requirements with qualified professionals. Do not use demo medicine listings for real medical decisions.

## Features

- Responsive pharmacy-first homepage with search, medicine detail pages, price comparison, and pharmacy finder.
- Customer accounts, saved medicines/pharmacies, address book, privacy controls, and order history.
- Pharmacy owner registration, licence details, verification, medicine listings, stock quantities, batch/expiry information, delivery or pickup options.
- Cart and checkout grouped by store; checkout reserves stock to prevent overselling. Completing an order consumes reserved quantity; cancelling or rejecting eligible orders releases it.
- Prescription upload (JPG, PNG, PDF) and pharmacy review for products that require it. A file upload does not itself approve a prescription.
- Internal pharmacy inventory: medicine register, batch/expiry tracking, low-stock/reorder suggestions, stock movement history, counter sales, receipt generation, and automatic stock deduction for recorded sales.
- Django Admin and an admin dashboard for pharmacy verification, medicine catalogue, listings, orders and audit activity.
- Responsive MedMitra interface with a persistent Light mode / Dark mode switch across the public pages.
- Development media serving blocks the private prescription directory from public `/media/` URLs.
- SQLite local setup, PostgreSQL support via `DATABASE_URL`, WhiteNoise static files and Render configuration.

## Main URLs

| URL | Purpose |
|---|---|
| `/` | Pharmacy marketplace home |
| `/medicines/` | Search and compare medicine listings |
| `/pharmacies/` | Find verified pharmacies |
| `/cart/` | Customer cart |
| `/customer/` | Customer medicine orders |
| `/prescriptions/` | Upload and view private prescription files |
| `/retailer/register/` | Register a pharmacy store |
| `/retailer/` | Store order/listing dashboard |
| `/retailer/listings/` | Manage online medicine listings |
| `/retailer/orders/` | Process customer orders |
| `/pharmacy/` | Internal inventory/POS dashboard (approved pharmacy staff or administrator) |
| `/pharmacy/medicines/` | Internal inventory register |
| `/pharmacy/stock/` | Inventory movement history |
| `/pharmacy/sales/new/` | Record a counter sale |
| `/admin-dashboard/` | Platform administration dashboard |
| `/admin/` | Django Admin |
| `/health/` | Deployment health check |

## Local setup (Windows PowerShell)

Use a supported recent Python version (the project dependencies were also installed successfully under Python 3.14 in the user-provided setup log). Extract the ZIP, open the extracted `MedMitra` folder in VS Code, and open the terminal in the same folder as `manage.py`.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py check
python manage.py createsuperuser
python manage.py runserver
```

Open **http://127.0.0.1:8000/**. For local development, `DJANGO_DEBUG` defaults to `True` when no deployment environment or `DATABASE_URL` is configured, so the Django test client and local HTTP server do not get forced through HTTPS. You can also copy `.env.example` to `.env` and set `DJANGO_DEBUG=True`. The deployed environment should explicitly set `DJANGO_DEBUG=False` and use HTTPS. Never commit `.env`, database files, uploaded documents, or production credentials.

## Sample catalogue data (optional)

To populate the UI with clearly fictional items for local testing, run:

```powershell
python manage.py seed_marketplace_demo
```

To also create fictional test store accounts and store listings, run `python manage.py seed_marketplace_demo --create-demo-users`. This prints temporary credentials for local testing. Do not use seeded products, stores, licence values, prices, or stock in real transactions; do not run the demo-user option on a production deployment.

## Inventory notes

The internal pharmacy inventory and the online marketplace store listings serve two different workflows. Counter sales deduct from the internal `Medicine` inventory and write `StockMovement` entries. Online orders reserve each store listing during checkout and consume that listing quantity once the order reaches Completed. Low-stock suggestions and expiry alerts are calculated from saved inventory records whenever the inventory dashboard loads; the app does not automatically place supplier purchase orders.

For real deployment, set a strong `DJANGO_SECRET_KEY`, exact `DJANGO_ALLOWED_HOSTS`, and a managed PostgreSQL `DATABASE_URL`. Configure secure persistent private storage for uploaded files, malware scanning, verified payment/delivery integrations, backups, monitoring and a tested access-control policy before processing real orders or prescription documents.

## Homepage content (superuser-managed)

The refreshed homepage follows the provided pharmacy-commerce reference: search-first hero, admin-managed featured offers, wellness category tiles, “New Launches” and “Trending Near You” product rails, local pharmacy listings, a full-width MedMitra Plus “coming soon” banner, image-only horizontal banner rail, editable MedMitra Difference heading/cards, customer reviews, and a multi-column footer. Product cards support admin-uploaded images; live local listings prioritize the pharmacy owner’s image and fall back to the shared catalogue image. Sample launch/trending prices are visibly marked and must be verified or replaced before any real use.

Sign in to `/admin/` with a Django superuser. The homepage content tools are visible only to superusers; ordinary staff accounts, pharmacy owners and customers cannot create, edit, publish or delete this content. After applying migrations, manage these sections in the admin:

- **Homepage promotions / advertisements**: upload banners, add accessible alt text, set optional destination links and start/end times, and arrange their scroll order.
- **Homepage trust metrics**: add honest, supportable numbers or benefits for the “Why choose us?” strip. Do not copy another pharmacy's business metrics.
- **Homepage customer reviews**: add genuine reviews only when you have permission to publish them. Reviews are hidden until `is_published` is enabled.
- **Homepage popular search terms**: organise terms into healthcare products, medicines, frequently searched medicines or vaccines. Terms link to MedMitra search unless you specify a custom URL.
- **Homepage information / SEO sections**: write your own service overview and useful, accurate information. The first active section with a non-empty SEO description becomes the homepage meta description.

After extracting a new project copy, run `python manage.py migrate`, create a superuser with `python manage.py createsuperuser`, then use `/admin/`. Uploaded banner files are served locally in `DEBUG=True`; the development media route explicitly blocks `private_prescriptions/`. Prescription files must still be served only through the permission-checked prescription download view. On production hosting, configure durable media/object storage before relying on uploaded banner images because local Render filesystem changes may not persist across deploys. Do not point a public CDN or web server at the private prescription directory.

## Footer social links (superuser-controlled)

The site brand is **MedMitra**. To add social links to the public footer, run `python manage.py migrate`, sign in at `/admin/` as a Django superuser, then open **Marketplace → Footer social media links**. Add the platform and its public HTTP(S) URL, select an order, and leave it active to publish. Use the active checkbox to hide links without deleting them. The footer social section is not shown until at least one link is active. Regular staff and pharmacy owners do not have permission to manage this content.



## Latest maintenance and verification

- The public site and Django Admin default to a light theme and ignore legacy saved dark-mode selections.
- Generic development media URLs deny access to `private_prescriptions/` and reject parent-directory traversal.
- A regression test covers those private-media protections.
- From the project root, run `python manage.py check`, `python manage.py makemigrations --check --dry-run`, and `python manage.py test` after installing `requirements.txt`. These runtime checks must be executed in an environment where the dependencies can be installed; do not treat Python syntax compilation alone as a substitute.

## Medicine photos and homepage advertisements

- **Platform administrator:** In `/admin/` → Marketplace → Medicine products, upload a shared catalogue image for a medicine. In `/admin/` → Marketplace → Homepage promotions / advertisements, upload a banner, set alt text, an optional destination, active status and schedule.
- **Pharmacy shop owner:** In Store orders → Medicine listings → Add medicine / Edit, upload an optional store-specific medicine photo. In Inventory → Add medicine / Edit, staff can upload a separate photo for the internal stock register.
- Homepage advertisement cards appear below the homepage hero. The separate image-only banner rail appears farther down the page and contains no displayed title or description. Only active promotions inside their optional start/end schedule are shown.
- Run `python manage.py migrate` after updating. Medicine images accept JPG, PNG or WebP and are limited to 5 MB in the shop/inventory forms. For production, configure durable media storage; do not serve private prescription files from public media URLs.
