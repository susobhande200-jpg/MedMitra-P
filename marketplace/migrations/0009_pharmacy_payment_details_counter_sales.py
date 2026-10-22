import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0008_online_and_qr_payments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="marketplaceorder",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("cash_on_delivery", "Cash on delivery (COD)"),
                    ("pay_at_store", "Pay by pharmacy QR / bank transfer (pickup)"),
                    ("razorpay", "Online payment — Razorpay"),
                    ("sbi_qr", "Pay by SBI Pay / UPI QR"),
                ], default="pay_at_store", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="pharmacy",
            name="payment_qr_image",
            field=models.ImageField(blank=True, upload_to="payment/pharmacy_qr/"),
        ),
        migrations.AddField(
            model_name="pharmacy",
            name="upi_id",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="pharmacy",
            name="bank_account_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="pharmacy",
            name="bank_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="pharmacy",
            name="bank_account_number",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="pharmacy",
            name="bank_ifsc_code",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="pharmacy",
            name="payment_instructions",
            field=models.CharField(blank=True, default="Pay the exact order total and upload your transaction proof.", max_length=300),
        ),
        migrations.CreateModel(
            name="PharmacyCounterSale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("receipt_number", models.CharField(max_length=32, unique=True)),
                ("public_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("customer_name", models.CharField(blank=True, max_length=160)),
                ("payment_method", models.CharField(choices=[("cash", "Cash"), ("upi", "UPI"), ("card", "Card")], default="cash", max_length=12)),
                ("total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10, validators=[MinValueValidator(Decimal("0.00"))])),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="marketplace_counter_sales", to=settings.AUTH_USER_MODEL)),
                ("pharmacy", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="counter_sales", to="marketplace.pharmacy")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="pharmacycountersale",
            index=models.Index(fields=["pharmacy", "created_at"], name="mk_counter_sale_store_dt"),
        ),
        migrations.CreateModel(
            name="PharmacyCounterSaleItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("product_name_snapshot", models.CharField(max_length=260)),
                ("quantity", models.PositiveIntegerField(validators=[MinValueValidator(1)])),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=10, validators=[MinValueValidator(Decimal("0.00"))])),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="counter_sale_items", to="marketplace.pharmacylisting")),
                ("sale", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="marketplace.pharmacycountersale")),
            ],
        ),
    ]
