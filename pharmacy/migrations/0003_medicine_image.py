from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("pharmacy", "0002_customer_label")]

    operations = [
        migrations.AddField(
            model_name="medicine",
            name="image",
            field=models.ImageField(blank=True, upload_to="medicines/inventory/"),
        ),
    ]
