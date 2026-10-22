"""Bulk-import medicine products and pharmacy listings from a CSV file.

Usage:
    python manage.py import_medicines_csv medicines.csv
    python manage.py import_medicines_csv medicines.csv --update-existing

Required CSV columns:
    pharmacy, brand_name, mrp, selling_price, available_quantity

Optional columns:
    generic_name, strength, dosage_form, pack_size, manufacturer, category,
    description, requires_prescription, batch_number, expiry_date, active,
    reserved_quantity

`pharmacy` must match an existing Pharmacy name or slug. Products are matched by
brand_name + strength + dosage_form; missing products are created. Existing
pharmacy listings are skipped unless --update-existing is supplied.
"""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from marketplace.models import MedicineCategory, MedicineProduct, Pharmacy, PharmacyListing


def truthy(value, default=False):
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def money(value, field_name, row_number):
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"row {row_number}: '{field_name}' must be a valid amount")
    if amount <= 0:
        raise ValueError(f"row {row_number}: '{field_name}' must be greater than zero")
    return amount


def integer(value, field_name, row_number, default=0):
    if value is None or not str(value).strip():
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"row {row_number}: '{field_name}' must be a whole number")
    if number < 0:
        raise ValueError(f"row {row_number}: '{field_name}' cannot be negative")
    return number


class Command(BaseCommand):
    help = "Import medicine products and pharmacy listings from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("csv_file", help="Path to the medicine CSV file")
        parser.add_argument(
            "--update-existing", action="store_true",
            help="Update price, stock, batch, expiry and active status for existing listings",
        )

    def handle(self, *args, **options):
        path = Path(options["csv_file"]).expanduser()
        if not path.is_file():
            raise CommandError(f"CSV file not found: {path}")

        try:
            stream = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise CommandError(f"Could not open CSV file: {exc}") from exc

        required = {"pharmacy", "brand_name", "mrp", "selling_price", "available_quantity"}
        created_products = created_listings = updated_listings = skipped = failed = 0
        errors = []

        with stream:
            reader = csv.DictReader(stream)
            headers = {str(h or "").strip().lower() for h in (reader.fieldnames or [])}
            missing = required - headers
            if missing:
                raise CommandError("Missing required CSV columns: " + ", ".join(sorted(missing)))

            for row_number, raw in enumerate(reader, start=2):
                row = {str(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
                try:
                    with transaction.atomic():
                        pharmacy_key = row.get("pharmacy", "")
                        brand_name = row.get("brand_name", "")
                        if not pharmacy_key:
                            raise ValueError(f"row {row_number}: pharmacy is required")
                        if not brand_name:
                            raise ValueError(f"row {row_number}: brand_name is required")

                        pharmacy = Pharmacy.objects.filter(slug=pharmacy_key).first()
                        if pharmacy is None:
                            pharmacy = Pharmacy.objects.filter(name__iexact=pharmacy_key).first()
                        if pharmacy is None:
                            raise ValueError(f"row {row_number}: pharmacy '{pharmacy_key}' was not found")

                        strength = row.get("strength", "")
                        dosage_form = (row.get("dosage_form") or "tablet").lower()
                        valid_forms = {choice[0] for choice in MedicineProduct.DosageForm.choices}
                        if dosage_form not in valid_forms:
                            raise ValueError(
                                f"row {row_number}: invalid dosage_form '{dosage_form}'. "
                                f"Use one of: {', '.join(sorted(valid_forms))}"
                            )

                        category = None
                        category_name = row.get("category", "")
                        if category_name:
                            category_slug = slugify(category_name)[:100]
                            category, _ = MedicineCategory.objects.get_or_create(
                                slug=category_slug,
                                defaults={"name": category_name[:80]},
                            )

                        product = MedicineProduct.objects.filter(
                            brand_name__iexact=brand_name,
                            strength__iexact=strength,
                            dosage_form=dosage_form,
                        ).first()
                        if product is None:
                            product = MedicineProduct.objects.create(
                                brand_name=brand_name[:160],
                                generic_name=row.get("generic_name", "")[:160],
                                strength=strength[:80],
                                dosage_form=dosage_form,
                                pack_size=row.get("pack_size", "")[:80],
                                manufacturer=row.get("manufacturer", "")[:160],
                                category=category,
                                description=row.get("description", ""),
                                requires_prescription=truthy(row.get("requires_prescription"), False),
                                active=truthy(row.get("product_active"), True),
                            )
                            created_products += 1

                        mrp = money(row.get("mrp"), "mrp", row_number)
                        selling_price = money(row.get("selling_price"), "selling_price", row_number)
                        if selling_price > mrp:
                            raise ValueError(f"row {row_number}: selling_price cannot exceed mrp")
                        quantity = integer(row.get("available_quantity"), "available_quantity", row_number)
                        reserved = integer(row.get("reserved_quantity"), "reserved_quantity", row_number)
                        if reserved > quantity:
                            raise ValueError(f"row {row_number}: reserved_quantity cannot exceed available_quantity")

                        expiry = None
                        expiry_text = row.get("expiry_date", "")
                        if expiry_text:
                            try:
                                expiry = date.fromisoformat(expiry_text)
                            except ValueError:
                                raise ValueError(f"row {row_number}: expiry_date must use YYYY-MM-DD")

                        listing = PharmacyListing.objects.filter(pharmacy=pharmacy, product=product).first()
                        values = {
                            "mrp": mrp,
                            "selling_price": selling_price,
                            "available_quantity": quantity,
                            "reserved_quantity": reserved,
                            "batch_number": row.get("batch_number", "")[:80],
                            "expiry_date": expiry,
                            "active": truthy(row.get("active"), True),
                        }
                        if listing:
                            if not options["update_existing"]:
                                skipped += 1
                                continue
                            for field, value in values.items():
                                setattr(listing, field, value)
                            listing.save()
                            updated_listings += 1
                        else:
                            PharmacyListing.objects.create(pharmacy=pharmacy, product=product, **values)
                            created_listings += 1
                except Exception as exc:
                    failed += 1
                    errors.append(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f"Import complete. Products created: {created_products}; "
            f"listings created: {created_listings}; listings updated: {updated_listings}; "
            f"existing listings skipped: {skipped}; failed rows: {failed}."
        ))
        for error in errors:
            self.stderr.write(self.style.ERROR(error))
