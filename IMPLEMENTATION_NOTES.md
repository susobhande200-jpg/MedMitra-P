# MedMitra commerce UI and local-order workflow update

## Included changes

- Replaced the mobile three-line menu with a Bootstrap off-canvas navigation drawer that opens from the left; desktop navigation remains separate.
- Standardized footer social icons to consistent circular targets and removed the Featured Categories footer column.
- Removed the extra review/price/PIN benefit row and prescription/pharmacy CTA row from the homepage hero.
- Changed homepage category tiles to square cards in two horizontal-scroll rows. Product rails, review cards, image banners and popular-search chips are horizontal and responsive.
- Kept the "MedMitra Difference" heading and visibility controlled in Django Admin through Homepage Section Settings.
- Added admin-managed popular-search sections for Top Selling, Trending and Top Discounts, including optional destination URLs.
- Added per-product catalogue images and store-specific listing images for administrator/shop uploads.
- Added prescription-request fields for the customer's manually typed medicine names and optional preferred PIN. The match page only recommends a pharmacy when its current published listings match each entered name; PIN matches rank first, then the indicative sum for one unit of each item.
- Added POST-only prescription removal, prevented removal when linked to an order, and a callback-request workflow visible to administrators.
- Added a horizontal order progress rail, printable order receipt, cash-payment status and a controlled action for pharmacy owners to record cash collection.
- Delivery checkout is Cash on Delivery (COD); pickup checkout is cash at the pharmacy. No online payment gateway is claimed or simulated.
- Added a migration for the new prescription and offline payment fields and expanded automated tests for key order/prescription workflows.

## Important behaviour and limits

- The uploaded prescription file is private; this code does not perform OCR. Customers must enter the medicine names one per line to use full-basket matching. A pharmacy must verify the actual prescription and availability before accepting the order.
- A callback request is recorded for an administrator to follow up; the website does not place an automatic phone call.
- Medicine distance sorting requests browser location only after the customer clicks the button and uses store coordinates when available. It calculates straight-line distance, not road travel time. PIN filtering remains available.
- Store prices and availability are retailer-reported and can change. The home-page showcase entries are explicitly labelled sample catalogue data until administrators verify them. The site does not claim online payment was completed.
- Prescription images/documents remain private and can only be removed if not linked to an order.

## Local verification

In the extracted project folder, activate the virtual environment, then run:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

Static verification for this ZIP includes Python source compilation, template control-tag balance, CSS parsing and SQLite integrity. The Django runtime checks and test suite could not be run in the build environment because Django was not installed and package downloads were blocked by unavailable network DNS. Run the commands above locally before deploying.
