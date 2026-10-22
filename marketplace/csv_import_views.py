"""CSV import workflow for pharmacy owners' marketplace listings.

The active pharmacy is selected from the authenticated owner's pharmacies; a CSV
cannot choose a different pharmacy or modify another owner's inventory.
"""
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import (
    MarketplaceAuditLog,
    MedicineCategory,
    MedicineProduct,
    Pharmacy,
    PharmacyListing,
)

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 5000

# Accept common spreadsheet header variants while keeping the downloaded template
# aligned with the existing MedMitra MedicineProduct and PharmacyListing models.
HEADER_ALIASES = {
    "medicine_name": "brand_name",
    "product_name": "brand_name",
    "name": "brand_name",
    "brand": "brand_name",
    "generic": "generic_name",
    "form": "dosage_form",
    "dosage": "dosage_form",
    "pack": "pack_size",
    "price": "selling_price",
    "sell_price": "selling_price",
    "sellingprice": "selling_price",
    "maximum_retail_price": "mrp",
    "stock": "available_quantity",
    "quantity": "available_quantity",
    "available_stock": "available_quantity",
    "batch": "batch_number",
    "expiry": "expiry_date",
    "prescription_required": "requires_prescription",
}

TEMPLATE_HEADERS = [
    "brand_name", "generic_name", "strength", "dosage_form", "pack_size",
    "manufacturer", "category", "requires_prescription", "mrp",
    "selling_price", "available_quantity", "batch_number", "expiry_date", "active",
]


def _owner_pharmacies(user):
    pharmacies = Pharmacy.objects.all() if (user.is_staff or user.is_superuser) else Pharmacy.objects.filter(owner=user)
    return pharmacies.order_by("created_at", "pk")


def _parse_bool(value, *, default=False, field_name="value"):
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return default
    if cleaned in {"1", "true", "yes", "y", "on", "required"}:
        return True
    if cleaned in {"0", "false", "no", "n", "off", "not required"}:
        return False
    raise ValueError(f"{field_name} must be yes/no or true/false.")


def _parse_date(value):
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError("expiry_date must be YYYY-MM-DD (also accepts DD/MM/YYYY).")


def _normalise_headers(headers):
    result = {}
    for header in headers or []:
        key = (header or "").strip().lower().replace(" ", "_").replace("-", "_")
        result[HEADER_ALIASES.get(key, key)] = header
    return result


def _write_import_audit(user, listing, action):
    MarketplaceAuditLog.objects.create(
        actor=user,
        action=action,
        object_type=listing._meta.label_lower,
        object_id=str(listing.pk),
        details=f"CSV inventory import for pharmacy #{listing.pharmacy_id}; product #{listing.product_id}"[:500],
    )


@login_required
def retailer_listing_csv_import(request):
    """Import medicine catalogue details and this owner's stock from a CSV file."""
    pharmacies = _owner_pharmacies(request.user)
    pharmacy_id = (request.GET.get("pharmacy") or request.POST.get("pharmacy_id") or "").strip()
    if not pharmacies.exists():
        messages.info(request, "Register your pharmacy before importing inventory.")
        return redirect("retailer_register")
    if pharmacy_id:
        pharmacy = get_object_or_404(pharmacies, pk=pharmacy_id)
    else:
        pharmacy = pharmacies.first()

    # The same restriction used by the listing form applies here.
    if pharmacy.verification_status in {Pharmacy.VerificationStatus.REJECTED, Pharmacy.VerificationStatus.SUSPENDED}:
        messages.error(request, "CSV imports are unavailable while this pharmacy is rejected or suspended. Contact the administrator for review.")
        return redirect("retailer_listings")

    if request.GET.get("download") == "template":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="medmitra_medicine_import_template.csv"'
        writer = csv.writer(response)
        writer.writerow(TEMPLATE_HEADERS)
        return response

    errors = []
    summary = None
    if request.method == "POST":
        uploaded = request.FILES.get("csv_file")
        update_existing = request.POST.get("update_existing") == "on"
        if not uploaded:
            errors.append("Choose a CSV file to upload.")
        elif uploaded.size > MAX_CSV_BYTES:
            errors.append("The CSV file is too large. Maximum size is 5 MB.")
        elif not uploaded.name.lower().endswith(".csv"):
            errors.append("Upload a .csv file. Excel workbooks must first be saved as CSV UTF-8.")

        reader = None
        if not errors:
            try:
                decoded = uploaded.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(decoded, newline=""))
            except UnicodeDecodeError:
                errors.append("The CSV must be saved as UTF-8 or CSV UTF-8.")
            except (csv.Error, UnicodeError):
                errors.append("The CSV file could not be read. Please save it as CSV UTF-8 and try again.")

        if reader is not None and not errors:
            headers = _normalise_headers(reader.fieldnames)
            if not reader.fieldnames or "brand_name" not in headers:
                errors.append("Missing medicine name column. Use brand_name, medicine_name or product_name.")
            for required in ("mrp", "selling_price", "available_quantity"):
                if required not in headers:
                    errors.append(f"Missing required column: {required}.")
            if errors:
                reader = None

        if reader is not None and not errors:
            created_products = created_listings = updated_listings = skipped_listings = failed_rows = processed_rows = 0
            row_errors = []
            for row_number, raw_row in enumerate(reader, start=2):
                if row_number > MAX_CSV_ROWS + 1:
                    row_errors.append(f"Row limit exceeded: upload no more than {MAX_CSV_ROWS} data rows per file.")
                    failed_rows += 1
                    break
                # Ignore entirely blank lines.
                if not raw_row or not any((v or "").strip() for v in raw_row.values() if isinstance(v, str)):
                    continue
                processed_rows += 1
                row = {}
                for normalised, original in headers.items():
                    row[normalised] = (raw_row.get(original) or "").strip()

                try:
                    brand_name = row.get("brand_name", "").strip()
                    if not brand_name:
                        raise ValueError("brand_name is required.")
                    if len(brand_name) > 160:
                        raise ValueError("brand_name must be 160 characters or fewer.")

                    generic_name = row.get("generic_name", "")[:160]
                    strength = row.get("strength", "")[:80]
                    dosage_form = (row.get("dosage_form") or "tablet").strip().lower()
                    dosage_aliases = {
                        "tablet": "tablet", "tablets": "tablet", "capsule": "capsule", "capsules": "capsule",
                        "syrup / liquid": "syrup", "liquid": "syrup", "syrup": "syrup",
                        "injection": "injection", "cream / ointment": "cream", "ointment": "cream", "cream": "cream",
                        "drops": "drops", "drop": "drops", "inhaler": "inhaler", "device": "device", "medical device": "device", "other": "other",
                    }
                    dosage_form = dosage_aliases.get(dosage_form, dosage_form)
                    allowed_forms = {value for value, _label in MedicineProduct.DosageForm.choices}
                    if dosage_form not in allowed_forms:
                        raise ValueError("dosage_form must be tablet, capsule, syrup, injection, cream, drops, inhaler, device or other.")

                    try:
                        mrp = Decimal(row.get("mrp", ""))
                        selling_price = Decimal(row.get("selling_price", ""))
                    except (InvalidOperation, TypeError):
                        raise ValueError("mrp and selling_price must be valid numbers.")
                    if not mrp.is_finite() or not selling_price.is_finite() or mrp <= 0 or selling_price <= 0:
                        raise ValueError("mrp and selling_price must be greater than zero.")
                    if selling_price > mrp:
                        raise ValueError("selling_price cannot exceed mrp.")
                    try:
                        available_quantity = int(row.get("available_quantity", ""))
                    except (TypeError, ValueError):
                        raise ValueError("available_quantity must be a whole number (0 or higher).")
                    if available_quantity < 0:
                        raise ValueError("available_quantity cannot be negative.")

                    batch_number = row.get("batch_number", "")[:80]
                    expiry_date = _parse_date(row.get("expiry_date", ""))
                    is_active = _parse_bool(row.get("active", ""), default=True, field_name="active")
                    # When updating existing rows, an omitted optional CSV column
                    # should not erase that field. A present-but-blank column can
                    # intentionally clear batch/expiry values.
                    batch_column_present = "batch_number" in headers
                    expiry_column_present = "expiry_date" in headers
                    active_value_present = "active" in headers and bool(row.get("active", "").strip())
                    requires_prescription = _parse_bool(row.get("requires_prescription", ""), default=False, field_name="requires_prescription")
                    pack_size = row.get("pack_size", "")[:80]
                    manufacturer = row.get("manufacturer", "")[:160]

                    category = None
                    category_name = row.get("category", "").strip()
                    if category_name:
                        category = MedicineCategory.objects.filter(name__iexact=category_name, active=True).first()
                        if category is None:
                            raise ValueError(f"Category '{category_name}' was not found or is inactive. Leave category blank or create it first.")

                    # Match a medicine using its key catalogue fields. Product names
                    # are global; price, stock and batch data remain pharmacy-specific.
                    product = MedicineProduct.objects.filter(
                        brand_name__iexact=brand_name,
                        strength__iexact=strength,
                        dosage_form=dosage_form,
                    ).order_by("pk").first()
                    product_was_created = False

                    with transaction.atomic():
                        if product is None:
                            product = MedicineProduct.objects.create(
                                brand_name=brand_name,
                                generic_name=generic_name,
                                strength=strength,
                                dosage_form=dosage_form,
                                pack_size=pack_size,
                                manufacturer=manufacturer,
                                category=category,
                                requires_prescription=requires_prescription,
                                active=True,
                            )
                            product_was_created = True

                        existing_listing = PharmacyListing.objects.filter(pharmacy=pharmacy, product=product).first()
                        if existing_listing and not update_existing:
                            skipped_listings += 1
                            continue

                        if existing_listing:
                            if available_quantity < existing_listing.reserved_quantity:
                                raise ValueError(
                                    f"available_quantity cannot be less than the {existing_listing.reserved_quantity} units already reserved."
                                )
                            existing_listing.mrp = mrp
                            existing_listing.selling_price = selling_price
                            existing_listing.available_quantity = available_quantity
                            if batch_column_present:
                                existing_listing.batch_number = batch_number
                            if expiry_column_present:
                                existing_listing.expiry_date = expiry_date
                            if active_value_present:
                                existing_listing.active = is_active
                            existing_listing.full_clean()
                            existing_listing.save()
                            _write_import_audit(request.user, existing_listing, "listing_saved")
                            updated_listings += 1
                        else:
                            listing = PharmacyListing(
                                pharmacy=pharmacy,
                                product=product,
                                mrp=mrp,
                                selling_price=selling_price,
                                available_quantity=available_quantity,
                                reserved_quantity=0,
                                batch_number=batch_number,
                                expiry_date=expiry_date,
                                active=is_active,
                            )
                            listing.full_clean()
                            listing.save()
                            _write_import_audit(request.user, listing, "listing_saved")
                            created_listings += 1
                        if product_was_created:
                            created_products += 1
                except (ValueError, ValidationError, InvalidOperation, IntegrityError) as exc:
                    failed_rows += 1
                    detail = " ".join(getattr(exc, "messages", [str(exc)])) if isinstance(exc, ValidationError) else str(exc)
                    row_errors.append(f"Row {row_number}: {detail}")

            summary = {
                "processed_rows": processed_rows,
                "created_products": created_products,
                "created_listings": created_listings,
                "updated_listings": updated_listings,
                "skipped_listings": skipped_listings,
                "failed_rows": failed_rows,
            }
            if failed_rows:
                messages.warning(request, f"CSV import finished with {failed_rows} failed row(s). Successful rows were saved; review the row errors below.")
            else:
                messages.success(request, "CSV import completed successfully.")
            errors.extend(row_errors[:100])

    return render(request, "marketplace/retailer_csv_import.html", {
        "pharmacy": pharmacy,
        "summary": summary,
        "errors": errors,
        "max_csv_mb": MAX_CSV_BYTES // (1024 * 1024),
        "max_csv_rows": MAX_CSV_ROWS,
    })
