from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone


def seed_curated_search_terms(apps, schema_editor):
    """Show editable starter chips without representing them as live sales analytics."""
    SearchTerm = apps.get_model("marketplace", "HomepageSearchTerm")
    db = schema_editor.connection.alias
    starter_terms = [
        ("top_selling", "Pain relief", "/medicines/?q=pain%20relief", 10),
        ("top_selling", "Vitamins & supplements", "/medicines/?q=vitamin", 20),
        ("top_selling", "Digestive care", "/medicines/?q=digestive", 30),
        ("trending", "Skin care", "/medicines/?q=skin", 10),
        ("trending", "Health devices", "/medicines/?q=device", 20),
        ("trending", "Mother & baby care", "/medicines/?q=baby", 30),
        ("discounts", "Discounted vitamins", "/medicines/?sort=discount&q=vitamin", 10),
        ("discounts", "Discounted devices", "/medicines/?sort=discount&q=device", 20),
        ("discounts", "View biggest discounts", "/medicines/?sort=discount", 30),
    ]
    for section, term, target_url, sort_order in starter_terms:
        SearchTerm.objects.using(db).get_or_create(
            section=section,
            term=term,
            defaults={"target_url": target_url, "sort_order": sort_order, "is_active": True},
        )


def preserve_curated_search_terms(apps, schema_editor):
    # Do not remove admin edits if this migration is reversed.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0006_homepage_commerce_content"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="prescription",
            name="requested_medicines",
            field=models.TextField(blank=True, help_text="Optional: enter one requested medicine name per line so the site can find pharmacies listing the full basket.", max_length=1200),
        ),
        migrations.AddField(
            model_name="prescription",
            name="preferred_pincode",
            field=models.CharField(blank=True, db_index=True, max_length=10),
        ),
        migrations.AddField(
            model_name="prescription",
            name="callback_requested",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="prescription",
            name="callback_phone",
            field=models.CharField(blank=True, max_length=25),
        ),
        migrations.AddField(
            model_name="prescription",
            name="callback_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="marketplaceorder",
            name="payment_method",
            field=models.CharField(choices=[("cash_on_delivery", "Cash on delivery (COD)"), ("pay_at_store", "Pay in cash at pharmacy")], default="pay_at_store", max_length=20),
        ),
        migrations.AddField(
            model_name="marketplaceorder",
            name="payment_status",
            field=models.CharField(choices=[("pending", "Payment due at fulfilment"), ("collected", "Cash collected")], db_index=True, default="pending", max_length=16),
        ),
        migrations.AddField(
            model_name="marketplaceorder",
            name="payment_collected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="marketplaceorder",
            name="payment_collected_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marketplace_cash_collections", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="homepagesearchterm",
            name="section",
            field=models.CharField(choices=[("healthcare", "Top-selling healthcare products (curated)"), ("medicines", "Top-selling medicines (curated)"), ("searched", "Top-searched medicines"), ("vaccines", "Top-searched vaccines"), ("top_selling", "Top selling — admin curated"), ("trending", "Trending — admin curated"), ("discounts", "Top discounts — admin curated")], db_index=True, max_length=20),
        ),
        migrations.RunPython(seed_curated_search_terms, preserve_curated_search_terms),
    ]
