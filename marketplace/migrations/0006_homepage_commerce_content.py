from decimal import Decimal
from django.db import migrations, models
import django.core.validators
import django.utils.timezone
import django.utils.text
import marketplace.models


def seed_homepage_content(apps, schema_editor):
    Section = apps.get_model("marketplace", "HomepageSectionSetting")
    Category = apps.get_model("marketplace", "HomepageCategoryTile")
    MedicineCategory = apps.get_model("marketplace", "MedicineCategory")
    Showcase = apps.get_model("marketplace", "HomepageShowcaseProduct")
    Plus = apps.get_model("marketplace", "HomepageMembershipBanner")
    Metric = apps.get_model("marketplace", "HomepageTrustMetric")
    db = schema_editor.connection.alias

    settings = [
        ("offers", "FEATURED OFFERS", "Offers and updates", "Promotions and announcements from MedMitra."),
        ("categories", "EXPLORE YOUR WELLNESS", "Shop by Category", "Find health and personal care essentials by category."),
        ("new_launches", "JUST ARRIVED", "New Launches", "New wellness range just for you!"),
        ("trending", "POPULAR PICKS", "Trending Near You", "Popular in your city."),
        ("local_listings", "LOCAL PHARMACIES", "Available from local pharmacies", "Retailer-reported prices and availability from participating stores."),
        ("image_banners", "", "", ""),
        ("difference", "THE MEDMITRA DIFFERENCE", "Why choose us?", "Clearer choices for discovering medicines and participating pharmacies."),
        ("testimonials", "CUSTOMER VOICES", "What Our Customers Have to Say", "Reviews are displayed after the MedMitra team verifies and approves them."),
    ]
    for key, eyebrow, title, description in settings:
        Section.objects.using(db).get_or_create(
            key=key,
            defaults={"eyebrow": eyebrow, "title": title, "description": description, "is_active": True},
        )

    categories = [
        ("Health Must Haves", "bi-heart-pulse", "Everyday wellness essentials"),
        ("Breathe Easy", "bi-wind", "Respiratory care essentials"),
        ("Skin Care", "bi-droplet-half", "Skin and body care"),
        ("Vitamins & Supplements", "bi-capsule", "Vitamins and supplements"),
        ("Healthcare Devices", "bi-thermometer-half", "Health monitoring devices"),
        ("Sexual Wellness", "bi-heart", "Intimate wellness products"),
        ("Sports Nutrition", "bi-activity", "Active lifestyle nutrition"),
        ("Pet Care", "bi-emoji-smile", "Care for companion animals"),
        ("Diabetes Essentials", "bi-droplet", "Diabetes care essentials"),
        ("Health Food and Drinks", "bi-cup-straw", "Nutrition and wellness drinks"),
        ("Homeopathy Care", "bi-flower1", "Homeopathy products"),
        ("Ayurvedic Care", "bi-flower2", "Ayurvedic wellness products"),
        ("Health Concern", "bi-clipboard2-pulse", "Browse by health need"),
        ("Mother and Baby Care", "bi-balloon-heart", "Care for mothers and babies"),
        ("Personal Care", "bi-stars", "Personal care essentials"),
        ("Explore More", "bi-grid", "Explore more categories"),
    ]
    for order, (name, icon, subtitle) in enumerate(categories, start=1):
        catalog_slug = django.utils.text.slugify(name)[:100] or f"category-{order}"
        catalog_category, _ = MedicineCategory.objects.using(db).get_or_create(
            name=name,
            defaults={"slug": catalog_slug, "description": subtitle, "icon": icon, "active": True},
        )
        if not catalog_category.slug:
            catalog_category.slug = catalog_slug
            catalog_category.save(update_fields=["slug"], using=db)
        tile_target = "/medicines/" if name == "Explore More" else f"/medicines/?category={catalog_category.slug}"
        Category.objects.using(db).get_or_create(
            name=name,
            defaults={"icon": icon, "subtitle": subtitle, "target_url": tile_target, "sort_order": order * 10, "is_active": True},
        )

    # All imported price cards are explicitly labelled sample catalogue entries in the UI.
    # Replace or deactivate them from the admin before treating any price as a live offer.
    products = [
        ("new_launches", "Mintop Shampoo +", "For Hairfall Control · 225 ml", "699.00", "623.00"),
        ("new_launches", "Dulcoflex Liquid", "Saunf flavour · 150 ml", "150.00", None),
        ("new_launches", "Yuderma Melarid-TRX Serum", "pH 3.5 · Melano correction · 40 ml", "1350.00", None),
        ("new_launches", "Ageasy Automatic Digital Blood Pressure Machine", "Max Group · Battery / USB Type-C", "1405.00", "1082.00"),
        ("new_launches", "Protinex Diabetes Care", "Chocolate flavour · 200 g", "360.00", "353.00"),
        ("new_launches", "Bioderma Sensibio Soothing Cleansing Gel", "For sensitive skin · 100 ml", "749.00", "712.00"),
        ("new_launches", "Baidyanath Asli Ayurved Mahayograj Guggulu", "100 tablets", "835.00", "794.00"),
        ("new_launches", "Thyrocare Pregnancy Test Kit", "Rapid test · 1 unit", "60.00", "54.00"),
        ("new_launches", "Venusia Ceraplus Lotion", "Dry skin · Pack of 2 · 200 ml total", "870.00", "714.00"),
        ("new_launches", "Health OK HMB", "Vanilla · Protein powder · 200 g", "949.00", "893.00"),
        ("trending", "Shelcal 500 mg", "Strip of 15 tablets", "164.00", "154.00"),
        ("trending", "Abzorb Total Skin Relief Dusting Powder", "120 g bottle", "164.00", "158.00"),
        ("trending", "Liveasy Wellness Calcium Magnesium Vitamin D3 & Zinc", "Bottle of 60 tablets", "533.00", "310.00"),
        ("trending", "Evion 400 mg Vitamin E", "Strip of 20 capsules", "99.00", "95.00"),
        ("trending", "Revital Men Complete Multivitamin", "With natural ginseng · 60 capsules", "600.00", "582.00"),
        ("trending", "Dr. Morepen Gluco One BG-03 Test Strips", "Blood glucose · 50 test strips", "795.00", "605.00"),
        ("trending", "Everherb Shilajit 500 mg", "Bottle of 60 · Catalogue sample", "937.00", "506.00"),
        ("trending", "Supradyn Daily Multivitamin", "Strip of 15 tablets", "75.00", "72.00"),
    ]
    for order, (section, name, subtitle, mrp, price) in enumerate(products, start=1):
        Showcase.objects.using(db).get_or_create(
            section=section, name=name,
            defaults={
                "subtitle": subtitle,
                "mrp": Decimal(mrp),
                "price": Decimal(price) if price is not None else None,
                "is_sample": True,
                "is_active": True,
                "sort_order": order * 10,
            },
        )

    Plus.objects.using(db).get_or_create(
        title="MedMitra Plus is coming soon",
        defaults={
            "eyebrow": "A NEW WAY TO CARE",
            "description": "A thoughtful new member experience is on the way. Stay tuned for what’s next.",
            "button_label": "Coming soon",
            "is_active": True,
            "sort_order": 10,
        },
    )

    trust_metrics = [
        ("Local", "Pharmacy choices", "Discover participating pharmacies after approval."),
        ("Clear", "Price comparison", "Compare retailer-reported prices before visiting."),
        ("Helpful", "Prescription-aware flow", "Upload a prescription where the workflow requires it."),
    ]
    for order, (value, label, detail) in enumerate(trust_metrics, start=1):
        Metric.objects.using(db).get_or_create(
            label=label,
            defaults={"value": value, "detail": detail, "icon": "bi-shield-check", "sort_order": order * 10, "is_active": True},
        )


def unseed_homepage_content(apps, schema_editor):
    # Deliberately retain published homepage content on reverse migration.
    pass


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0005_medicineproduct_image_pharmacylisting_image")]

    operations = [
        migrations.CreateModel(
            name="HomepageSectionSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(choices=[("offers", "Offers and updates"), ("categories", "Shop by category"), ("new_launches", "New launches"), ("trending", "Trending near you"), ("difference", "The MedMitra difference"), ("testimonials", "Customer testimonials"), ("local_listings", "Local pharmacy listings"), ("image_banners", "Image banner rail")], max_length=30, unique=True)),
                ("eyebrow", models.CharField(blank=True, max_length=100)),
                ("title", models.CharField(blank=True, max_length=180)),
                ("description", models.CharField(blank=True, max_length=280)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Homepage section heading", "verbose_name_plural": "Homepage section headings", "ordering": ["sort_order", "key"]},
        ),
        migrations.CreateModel(
            name="HomepageCategoryTile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("subtitle", models.CharField(blank=True, max_length=160)),
                ("icon", models.CharField(default="bi-heart-pulse", max_length=50)),
                ("image", models.ImageField(blank=True, upload_to="homepage/categories/")),
                ("target_url", models.CharField(blank=True, max_length=500, validators=[marketplace.models.validate_homepage_link])),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Homepage category tile", "verbose_name_plural": "Homepage category tiles", "ordering": ["sort_order", "name"]},
        ),
        migrations.CreateModel(
            name="HomepageShowcaseProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("section", models.CharField(choices=[("new_launches", "New launches"), ("trending", "Trending near you")], db_index=True, max_length=20)),
                ("name", models.CharField(max_length=220)),
                ("subtitle", models.CharField(blank=True, max_length=240)),
                ("image", models.ImageField(blank=True, help_text="Optional product image. Shop-specific images can also be uploaded on a pharmacy listing.", upload_to="homepage/products/")),
                ("mrp", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("price", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("target_url", models.CharField(blank=True, max_length=500, validators=[marketplace.models.validate_homepage_link])),
                ("is_sample", models.BooleanField(default=False, help_text="Show a sample-price label; enable this for unverified/demo catalogue data.")),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Homepage featured product", "verbose_name_plural": "Homepage featured products", "ordering": ["section", "sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="HomepageMembershipBanner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("eyebrow", models.CharField(blank=True, default="A NEW WAY TO CARE", max_length=100)),
                ("title", models.CharField(default="MedMitra Plus is coming soon", max_length=180)),
                ("description", models.CharField(blank=True, default="A thoughtful new member experience is on the way. Stay tuned for what’s next.", max_length=280)),
                ("button_label", models.CharField(blank=True, default="Coming soon", max_length=60)),
                ("button_url", models.CharField(blank=True, max_length=500, validators=[marketplace.models.validate_homepage_link])),
                ("image", models.ImageField(blank=True, upload_to="homepage/membership/")),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Homepage membership banner", "verbose_name_plural": "Homepage membership banners", "ordering": ["sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="HomepageImageBanner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="homepage/image-banners/")),
                ("alt_text", models.CharField(help_text="Describe the banner image for accessibility.", max_length=180)),
                ("target_url", models.CharField(blank=True, max_length=500, validators=[marketplace.models.validate_homepage_link])),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Homepage image-only banner", "verbose_name_plural": "Homepage image-only banners", "ordering": ["sort_order", "id"]},
        ),
        migrations.AlterField(
            model_name="homepageeditorialsection",
            name="eyebrow",
            field=models.CharField(blank=True, help_text="Optional small heading above the title.", max_length=100),
        ),
        migrations.RunPython(seed_homepage_content, unseed_homepage_content),
    ]
