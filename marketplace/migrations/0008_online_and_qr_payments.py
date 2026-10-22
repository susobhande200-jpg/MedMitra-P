from django.conf import settings
from django.core.validators import FileExtensionValidator
import django.db.models.deletion
from django.db import migrations, models
import marketplace.models
import marketplace.storage


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0007_prescription_matching_and_cash_payment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="marketplaceorder",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("cash_on_delivery", "Cash on delivery (COD)"),
                    ("pay_at_store", "Pay at pharmacy counter"),
                    ("razorpay", "Online payment — Razorpay"),
                    ("sbi_qr", "Pay by SBI Pay / UPI QR"),
                ], default="pay_at_store", max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="marketplaceorder",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("pending", "Payment pending"),
                    ("proof_submitted", "Payment proof submitted — awaiting review"),
                    ("proof_rejected", "Payment proof rejected — resubmission needed"),
                    ("paid", "Paid online"),
                    ("collected", "Cash collected"),
                ], db_index=True, default="pending", max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="marketplaceorder", name="gateway_order_id",
            field=models.CharField(blank=True, db_index=True, max_length=100),
        ),
        migrations.AddField(
            model_name="marketplaceorder", name="gateway_payment_id",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="marketplaceorder", name="payment_reference",
            field=models.CharField(blank=True, help_text="Optional UTR / bank transaction reference for QR transfers.", max_length=100),
        ),
        migrations.AddField(
            model_name="marketplaceorder", name="payment_proof",
            field=models.FileField(
                blank=True,
                help_text="Private proof attachment. Accessible only to the customer, assigned pharmacy and administrator.",
                upload_to=marketplace.models.private_payment_proof_path,
                storage=marketplace.storage.PrivateUploadStorage(),
                validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "pdf"])],
            ),
        ),
        migrations.AddField(
            model_name="marketplaceorder", name="payment_review_note",
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name="marketplaceorder", name="payment_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="marketplaceorder", name="payment_verified_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_payment_reviews", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="MarketplacePaymentSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(default="SBI Pay / UPI", max_length=100)),
                ("upi_id", models.CharField(blank=True, help_text="Optional verified UPI ID shown with the QR code.", max_length=100)),
                ("qr_image", models.ImageField(blank=True, help_text="Public payment QR image. Do not upload payment proof here.", upload_to="payment/qr_codes/")),
                ("instructions", models.CharField(blank=True, default="Pay the exact order total and upload your transaction proof.", max_length=300)),
                ("is_active", models.BooleanField(default=False, help_text="Enable QR checkout only after verifying the payee details.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Payment settings (SBI Pay / UPI QR)",
                "verbose_name_plural": "Payment settings (SBI Pay / UPI QR)",
            },
        ),
    ]
