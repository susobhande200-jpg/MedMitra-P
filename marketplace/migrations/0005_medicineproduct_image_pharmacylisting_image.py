from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0004_homepage_search_term_brand_help_text")]

    operations = [
        migrations.AddField(
            model_name="medicineproduct",
            name="image",
            field=models.ImageField(blank=True, upload_to="medicines/catalog/"),
        ),
        migrations.AddField(
            model_name="pharmacylisting",
            name="image",
            field=models.ImageField(blank=True, help_text="Optional store-specific medicine photo.", upload_to="medicines/listings/"),
        ),
    ]
