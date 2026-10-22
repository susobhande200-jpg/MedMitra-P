import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator, URLValidator
from .storage import PrivateUploadStorage
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def private_prescription_path(instance, filename):
    """Keep prescription documents away from public static/media URLs."""
    suffix = Path(filename).suffix.lower()
    return f"private_prescriptions/user_{instance.owner_id}/{uuid.uuid4().hex}{suffix}"


def private_payment_proof_path(instance, filename):
    """Store customer payment proofs outside the publicly served media root."""
    suffix = Path(filename).suffix.lower()
    return f"payment_proofs/order_{instance.pk or 'new'}/user_{instance.customer_id}/{uuid.uuid4().hex}{suffix}"


def validate_homepage_link(value):
    """Allow local site paths or absolute HTTP(S) links; reject script/data URLs."""
    if not value:
        return
    if value.startswith("/") and not value.startswith("//"):
        return
    URLValidator(schemes=["http", "https"])(value)


class MedicineCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.CharField(max_length=220, blank=True)
    icon = models.CharField(max_length=50, default="bi-capsule-pill")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Medicine categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:100] or f"category-{uuid.uuid4().hex[:8]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class MedicineProduct(models.Model):
    class DosageForm(models.TextChoices):
        TABLET = "tablet", "Tablet"
        CAPSULE = "capsule", "Capsule"
        SYRUP = "syrup", "Syrup / liquid"
        INJECTION = "injection", "Injection"
        CREAM = "cream", "Cream / ointment"
        DROPS = "drops", "Drops"
        INHALER = "inhaler", "Inhaler"
        DEVICE = "device", "Medical device"
        OTHER = "other", "Other"

        SOAP = "soap", "Soap"
        SHAMPOO = "shampoo", "Shampoo"
        HAIR_OIL = "hair_oil", "Hair oil"
        FACE_WASH = "face_wash", "Face wash"
        BABY_FOOD = "baby_food", "Baby food"
        NUTRITION_DRINK = "nutrition_drink", "Nutrition drink"
        GLUCOSE_POWDER = "glucose_powder", "Glucose powder"
        INFANT_FORMULA = "infant_formula", "Infant formula"
        PETROLEUM_JELLY = "petroleum_jelly", "Petroleum jelly"
        BANDAGE = "bandage", "Bandage"
        ORAL_POWDER = "oral_powder", "Oral powder"

    # Keep your existing MedicineProduct model fields here.

    brand_name = models.CharField(max_length=160, db_index=True)
    generic_name = models.CharField(max_length=160, blank=True, db_index=True)
    strength = models.CharField(max_length=80, blank=True)
    dosage_form = models.CharField(max_length=20, choices=DosageForm.choices, default=DosageForm.TABLET)
    pack_size = models.CharField(max_length=80, blank=True)
    manufacturer = models.CharField(max_length=160, blank=True)
    category = models.ForeignKey(MedicineCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="medicines/catalog/", blank=True)
    requires_prescription = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["brand_name", "strength"]
        indexes = [
            models.Index(fields=["brand_name", "strength"], name="mk_brand_strength_idx"),
            models.Index(fields=["generic_name", "active"], name="mk_generic_active_idx"),
        ]

    def __str__(self):
        pieces = [self.brand_name, self.strength, self.get_dosage_form_display()]
        return " · ".join(p for p in pieces if p)


class Pharmacy(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Verified"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Suspended"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_pharmacies")
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    phone = models.CharField(max_length=25)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=220)
    locality = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=100, default="Ghatal")
    state = models.CharField(max_length=100, default="West Bengal")
    pincode = models.CharField(max_length=10, db_index=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    licence_number = models.CharField(max_length=100, blank=True)
    licence_expiry = models.DateField(null=True, blank=True)
    pharmacist_name = models.CharField(max_length=160, blank=True)
    pharmacist_registration = models.CharField(max_length=100, blank=True)
    opening_time = models.TimeField(null=True, blank=True)
    closing_time = models.TimeField(null=True, blank=True)
    offers_delivery = models.BooleanField(default=True)
    offers_pickup = models.BooleanField(default=True)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0.00"))])
    # Store-configured payment destinations. Only shown to customers placing an order
    # with this pharmacy; Razorpay secrets are never stored on this model.
    payment_qr_image = models.ImageField(upload_to="payment/pharmacy_qr/", blank=True)
    upi_id = models.CharField(max_length=100, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=40, blank=True)
    bank_ifsc_code = models.CharField(max_length=20, blank=True)
    payment_instructions = models.CharField(max_length=300, blank=True, default="Pay the exact order total and upload your transaction proof.")
    verification_status = models.CharField(max_length=20, choices=VerificationStatus.choices, default=VerificationStatus.PENDING, db_index=True)
    verification_note = models.CharField(max_length=240, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["verification_status", "city", "pincode"], name="mk_status_city_pin_idx")]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:175] or "pharmacy"
            candidate = base
            number = 2
            while Pharmacy.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{number}"
                number += 1
            self.slug = candidate
        if self.verification_status == self.VerificationStatus.APPROVED and not self.verified_at:
            self.verified_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def verified(self):
        return self.verification_status == self.VerificationStatus.APPROVED

    @property
    def has_payment_destination(self):
        bank_ready = bool(self.bank_account_name and self.bank_name and self.bank_account_number and self.bank_ifsc_code)
        return bool(self.payment_qr_image or self.upi_id or bank_ready)

    @property
    def full_address(self):
        return ", ".join(part for part in [self.address, self.locality, self.city, self.state, self.pincode] if part)

    def __str__(self):
        return self.name


class PharmacyListing(models.Model):
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="listings")
    product = models.ForeignKey(MedicineProduct, on_delete=models.PROTECT, related_name="pharmacy_listings")
    mrp = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    image = models.ImageField(upload_to="medicines/listings/", blank=True, help_text="Optional store-specific medicine photo.")
    available_quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    batch_number = models.CharField(max_length=80, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    last_stock_update = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["selling_price", "product__brand_name"]
        constraints = [
            models.UniqueConstraint(fields=["pharmacy", "product"], name="uniq_listing_store_product"),
            models.CheckConstraint(condition=models.Q(selling_price__lte=models.F("mrp")), name="listing_sell_at_or_below_mrp"),
            models.CheckConstraint(condition=models.Q(reserved_quantity__lte=models.F("available_quantity")), name="listing_reserved_le_stock"),
        ]
        indexes = [models.Index(fields=["active", "available_quantity", "selling_price"], name="mk_listing_avail_price_idx")]

    def save(self, *args, **kwargs):
        self.last_stock_update = timezone.now()
        super().save(*args, **kwargs)

    @property
    def discount_percent(self):
        if not self.mrp:
            return 0
        return int(((self.mrp - self.selling_price) / self.mrp) * 100)

    @property
    def sellable_quantity(self):
        return max(0, self.available_quantity - self.reserved_quantity)

    @property
    def in_stock(self):
        return self.active and self.sellable_quantity > 0 and not self.is_expired

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    @property
    def inventory_is_fresh(self):
        return self.last_stock_update >= timezone.now() - timedelta(hours=6)

    def __str__(self):
        return f"{self.product} @ {self.pharmacy}"


class Prescription(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CLARIFICATION = "clarification", "More information required"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_prescriptions")
    file = models.FileField(upload_to=private_prescription_path, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"])])
    original_filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    customer_note = models.CharField(max_length=240, blank=True)
    requested_medicines = models.TextField(max_length=1200, blank=True, help_text="Optional: enter one requested medicine name per line so the site can find pharmacies listing the full basket.")
    preferred_pincode = models.CharField(max_length=10, blank=True, db_index=True)
    callback_requested = models.BooleanField(default=False, db_index=True)
    callback_phone = models.CharField(max_length=25, blank=True)
    callback_requested_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_prescriptions_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Prescription {self.pk} ({self.get_status_display()})"


class CartItem(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_cart_items")
    listing = models.ForeignKey(PharmacyListing, on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [models.UniqueConstraint(fields=["customer", "listing"], name="uniq_cart_customer_listing")]

    @property
    def subtotal(self):
        return self.quantity * self.listing.selling_price


class MarketplaceOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending pharmacy confirmation"
        ACCEPTED = "accepted", "Accepted"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready for pickup"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        REFUND_PENDING = "refund_pending", "Refund pending"
        REFUNDED = "refunded", "Refunded"

    class Fulfilment(models.TextChoices):
        DELIVERY = "delivery", "Home delivery"
        PICKUP = "pickup", "Store pickup"

    class PaymentMethod(models.TextChoices):
        COD = "cash_on_delivery", "Cash on delivery (COD)"
        PAY_AT_STORE = "pay_at_store", "Pay by pharmacy QR / bank transfer (pickup)"
        RAZORPAY = "razorpay", "Online payment — Razorpay"
        SBI_QR = "sbi_qr", "Pay by SBI Pay / UPI QR"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Payment pending"
        PROOF_SUBMITTED = "proof_submitted", "Payment proof submitted — awaiting review"
        PROOF_REJECTED = "proof_rejected", "Payment proof rejected — resubmission needed"
        PAID = "paid", "Paid online"
        COLLECTED = "collected", "Cash collected"

    reference = models.CharField(max_length=18, unique=True, blank=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_orders")
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.PROTECT, related_name="orders")
    prescription = models.ForeignKey(Prescription, on_delete=models.PROTECT, null=True, blank=True, related_name="orders")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True)
    fulfilment = models.CharField(max_length=12, choices=Fulfilment.choices, default=Fulfilment.PICKUP)
    delivery_address = models.CharField(max_length=300, blank=True)
    customer_note = models.CharField(max_length=300, blank=True)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.PAY_AT_STORE)
    payment_status = models.CharField(max_length=24, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True)
    payment_collected_at = models.DateTimeField(null=True, blank=True)
    payment_collected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_cash_collections")
    gateway_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    gateway_payment_id = models.CharField(max_length=100, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True, help_text="Optional UTR / bank transaction reference for QR transfers.")
    payment_proof = models.FileField(
        upload_to=private_payment_proof_path,
        storage=PrivateUploadStorage(),
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "pdf"])],
        blank=True,
        help_text="Private proof attachment. Accessible only to the customer, assigned pharmacy and administrator.",
    )
    payment_review_note = models.CharField(max_length=300, blank=True)
    payment_verified_at = models.DateTimeField(null=True, blank=True)
    payment_verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_payment_reviews")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "status", "created_at"], name="mk_order_cust_stat_dt"), models.Index(fields=["pharmacy", "status", "created_at"], name="mk_order_store_stat_dt")]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"MK{timezone.now():%y%m%d}{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    @property
    def can_customer_cancel(self):
        return self.status == self.Status.PENDING

    def __str__(self):
        return self.reference or f"Order {self.pk}"


class MarketplacePaymentSettings(models.Model):
    """Admin-configured public QR instructions; Razorpay secrets stay in environment variables."""
    display_name = models.CharField(max_length=100, default="SBI Pay / UPI")
    upi_id = models.CharField(max_length=100, blank=True, help_text="Optional verified UPI ID shown with the QR code.")
    qr_image = models.ImageField(upload_to="payment/qr_codes/", blank=True, help_text="Public payment QR image. Do not upload payment proof here.")
    instructions = models.CharField(max_length=300, blank=True, default="Pay the exact order total and upload your transaction proof.")
    is_active = models.BooleanField(default=False, help_text="Enable QR checkout only after verifying the payee details.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment settings (SBI Pay / UPI QR)"
        verbose_name_plural = "Payment settings (SBI Pay / UPI QR)"

    def save(self, *args, **kwargs):
        if self.is_active:
            MarketplacePaymentSettings.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def active_qr(cls):
        return cls.objects.filter(is_active=True).exclude(qr_image="").order_by("-updated_at", "-pk").first()

    def __str__(self):
        return f"{self.display_name} ({'active' if self.is_active else 'inactive'})"


class MarketplaceOrderItem(models.Model):
    order = models.ForeignKey(MarketplaceOrder, on_delete=models.CASCADE, related_name="items")
    listing = models.ForeignKey(PharmacyListing, on_delete=models.PROTECT, related_name="order_items")
    product_name_snapshot = models.CharField(max_length=260)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp_snapshot = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} × {self.product_name_snapshot}"


class PharmacyCounterSale(models.Model):
    """Walk-in sale made by a retailer against their marketplace listing stock."""
    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI"
        CARD = "card", "Card"

    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.PROTECT, related_name="counter_sales")
    receipt_number = models.CharField(max_length=32, unique=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer_name = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_counter_sales")
    payment_method = models.CharField(max_length=12, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0.00"))])
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["pharmacy", "created_at"], name="mk_counter_sale_store_dt")]

    def __str__(self):
        return self.receipt_number


class PharmacyCounterSaleItem(models.Model):
    sale = models.ForeignKey(PharmacyCounterSale, on_delete=models.CASCADE, related_name="items")
    listing = models.ForeignKey(PharmacyListing, on_delete=models.PROTECT, related_name="counter_sale_items")
    product_name_snapshot = models.CharField(max_length=260)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} × {self.product_name_snapshot}"


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(MarketplaceOrder, on_delete=models.CASCADE, related_name="status_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    old_status = models.CharField(max_length=24, blank=True)
    new_status = models.CharField(max_length=24)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.order.reference}: {self.old_status} → {self.new_status}"


class MarketplaceAuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_audit_events")
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    details = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at", "action"], name="mk_audit_time_action_idx"),
            models.Index(fields=["actor", "created_at"], name="mk_audit_actor_time_idx"),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} · {self.action} · {self.object_type} #{self.object_id}"


class HomepagePromotion(models.Model):
    """Admin-managed image promotion shown in the scrollable homepage rail."""
    title = models.CharField(max_length=140)
    subtitle = models.CharField(max_length=240, blank=True)
    image = models.ImageField(upload_to="homepage/promotions/")
    alt_text = models.CharField(max_length=180, help_text="Describe the image for accessibility.")
    target_url = models.CharField(max_length=500, blank=True, validators=[validate_homepage_link], help_text="Optional internal path (e.g. /medicines/) or absolute HTTP(S) destination.")
    button_label = models.CharField(max_length=60, blank=True, default="Explore offer")
    starts_at = models.DateTimeField(null=True, blank=True, help_text="Optional scheduled start in the site's timezone.")
    ends_at = models.DateTimeField(null=True, blank=True, help_text="Optional end time; the banner is hidden after this time.")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Homepage promotion / advertisement"
        verbose_name_plural = "Homepage promotions / advertisements"

    def __str__(self):
        return self.title


class HomepageTrustMetric(models.Model):
    """Admin-authored trust/benefit card; avoid publishing unverified claims."""
    value = models.CharField(max_length=60, help_text="Use a real, supportable value (or a short label).")
    label = models.CharField(max_length=100)
    detail = models.CharField(max_length=180, blank=True)
    icon = models.CharField(max_length=50, default="bi-shield-check", help_text="Bootstrap icon class, e.g. bi-shop.")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Homepage trust metric"
        verbose_name_plural = "Homepage trust metrics"

    def __str__(self):
        return f"{self.value} — {self.label}"


class HomepageTestimonial(models.Model):
    """Review text manually curated and published by a site superuser."""
    customer_name = models.CharField(max_length=100)
    location_label = models.CharField(max_length=100, blank=True)
    review_date = models.DateField(null=True, blank=True)
    quote = models.TextField(max_length=1200)
    rating = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(5)])
    is_published = models.BooleanField(default=False, help_text="Only publish genuine reviews you are authorised to display.")
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "-review_date", "id"]
        verbose_name = "Homepage customer review"
        verbose_name_plural = "Homepage customer reviews"

    def __str__(self):
        return f"{self.customer_name} ({self.rating}/5)"


class HomepageSearchTerm(models.Model):
    class Section(models.TextChoices):
        HEALTHCARE = "healthcare", "Top-selling healthcare products (curated)"
        MEDICINES = "medicines", "Top-selling medicines (curated)"
        SEARCHED = "searched", "Top-searched medicines"
        VACCINES = "vaccines", "Top-searched vaccines"
        TOP_SELLING = "top_selling", "Top selling — admin curated"
        TRENDING = "trending", "Trending — admin curated"
        DISCOUNTS = "discounts", "Top discounts — admin curated"

    section = models.CharField(max_length=20, choices=Section.choices, db_index=True)
    term = models.CharField(max_length=150)
    target_url = models.CharField(max_length=500, blank=True, validators=[validate_homepage_link], help_text="Optional internal path or absolute HTTP(S) destination. Otherwise, this term searches MedMitra.")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["section", "sort_order", "term"]
        verbose_name = "Homepage popular search term"
        verbose_name_plural = "Homepage popular search terms"

    def __str__(self):
        return f"{self.get_section_display()}: {self.term}"


class FooterSocialLink(models.Model):
    """A social profile link displayed in the MedMitra site footer.

    The Django admin is deliberately restricted to superusers for this model.
    """

    class Platform(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        FACEBOOK = "facebook", "Facebook"
        YOUTUBE = "youtube", "YouTube"
        LINKEDIN = "linkedin", "LinkedIn"
        X = "x", "X"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEGRAM = "telegram", "Telegram"
        OTHER = "other", "Other"

    platform = models.CharField(max_length=20, choices=Platform.choices)
    label = models.CharField(
        max_length=80,
        blank=True,
        help_text="Optional text shown beside the icon. If blank, the platform name is used.",
    )
    url = models.URLField(
        max_length=500,
        validators=[URLValidator(schemes=["http", "https"])],
        help_text="Public HTTP(S) profile or page URL. Script and data URLs are not allowed.",
    )
    open_in_new_tab = models.BooleanField(
        default=True,
        help_text="Open this external link in a new browser tab.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "platform", "id"]
        verbose_name = "Footer social media link"
        verbose_name_plural = "Footer social media links"

    @property
    def display_label(self):
        return self.label.strip() or self.get_platform_display()

    @property
    def icon_class(self):
        return {
            self.Platform.INSTAGRAM: "bi bi-instagram",
            self.Platform.FACEBOOK: "bi bi-facebook",
            self.Platform.YOUTUBE: "bi bi-youtube",
            self.Platform.LINKEDIN: "bi bi-linkedin",
            self.Platform.X: "bi bi-twitter-x",
            self.Platform.WHATSAPP: "bi bi-whatsapp",
            self.Platform.TELEGRAM: "bi bi-telegram",
            self.Platform.OTHER: "bi bi-link-45deg",
        }.get(self.platform, "bi bi-link-45deg")

    def __str__(self):
        return f"{self.display_label}: {self.url}"


class HomepageEditorialSection(models.Model):
    """Admin-managed SEO and informational copy displayed near the page bottom."""
    eyebrow = models.CharField(max_length=100, blank=True, help_text="Optional small heading above the title.")
    title = models.CharField(max_length=180)
    body = models.TextField(help_text="Plain text only; line breaks are displayed on the public homepage.")
    seo_description = models.CharField(max_length=255, blank=True, help_text="Optional homepage meta description. First active entry with this value is used.")
    button_label = models.CharField(max_length=60, blank=True)
    button_url = models.CharField(max_length=500, blank=True, validators=[validate_homepage_link])
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Homepage information / SEO section"
        verbose_name_plural = "Homepage information / SEO sections"

    def __str__(self):
        return self.title


class HomepageSectionSetting(models.Model):
    """Admin-editable headings and visibility controls for homepage sections."""

    class SectionKey(models.TextChoices):
        OFFERS = "offers", "Offers and updates"
        CATEGORIES = "categories", "Shop by category"
        NEW_LAUNCHES = "new_launches", "New launches"
        TRENDING = "trending", "Trending near you"
        DIFFERENCE = "difference", "The MedMitra difference"
        TESTIMONIALS = "testimonials", "Customer testimonials"
        LOCAL_LISTINGS = "local_listings", "Local pharmacy listings"
        IMAGE_BANNERS = "image_banners", "Image banner rail"

    key = models.CharField(max_length=30, choices=SectionKey.choices, unique=True)
    eyebrow = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=180, blank=True)
    description = models.CharField(max_length=280, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "key"]
        verbose_name = "Homepage section heading"
        verbose_name_plural = "Homepage section headings"

    def __str__(self):
        return self.title


class HomepageCategoryTile(models.Model):
    """Admin-managed category tiles on the homepage; image is optional."""
    name = models.CharField(max_length=100, unique=True)
    subtitle = models.CharField(max_length=160, blank=True)
    icon = models.CharField(max_length=50, default="bi-heart-pulse")
    image = models.ImageField(upload_to="homepage/categories/", blank=True)
    target_url = models.CharField(max_length=500, blank=True, validators=[validate_homepage_link])
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Homepage category tile"
        verbose_name_plural = "Homepage category tiles"

    def __str__(self):
        return self.name


class HomepageShowcaseProduct(models.Model):
    """Curated homepage catalog cards. Demo entries must be verified before real sale claims."""

    class Section(models.TextChoices):
        NEW_LAUNCHES = "new_launches", "New launches"
        TRENDING = "trending", "Trending near you"

    section = models.CharField(max_length=20, choices=Section.choices, db_index=True)
    name = models.CharField(max_length=220)
    subtitle = models.CharField(max_length=240, blank=True)
    image = models.ImageField(upload_to="homepage/products/", blank=True, help_text="Optional product image. Shop-specific images can also be uploaded on a pharmacy listing.")
    mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0.01"))])
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0.01"))])
    target_url = models.CharField(max_length=500, blank=True, validators=[validate_homepage_link])
    is_sample = models.BooleanField(default=False, help_text="Show a sample-price label; enable this for unverified/demo catalogue data.")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "sort_order", "id"]
        verbose_name = "Homepage featured product"
        verbose_name_plural = "Homepage featured products"

    def clean(self):
        super().clean()
        if self.price is not None and self.mrp is not None and self.price > self.mrp:
            from django.core.exceptions import ValidationError
            raise ValidationError({"price": "Price cannot be higher than MRP."})

    @property
    def discount_percent(self):
        if not self.price or not self.mrp or self.price >= self.mrp:
            return 0
        return int(((self.mrp - self.price) / self.mrp) * 100)

    def __str__(self):
        return self.name


class HomepageMembershipBanner(models.Model):
    """Wide, editable membership teaser; keep promises limited to approved copy."""
    eyebrow = models.CharField(max_length=100, blank=True, default="A NEW WAY TO CARE")
    title = models.CharField(max_length=180, default="MedMitra Plus is coming soon")
    description = models.CharField(max_length=280, blank=True, default="A thoughtful new member experience is on the way. Stay tuned for what’s next.")
    button_label = models.CharField(max_length=60, blank=True, default="Coming soon")
    button_url = models.CharField(max_length=500, blank=True, validators=[validate_homepage_link])
    image = models.ImageField(upload_to="homepage/membership/", blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Homepage membership banner"
        verbose_name_plural = "Homepage membership banners"

    def __str__(self):
        return self.title


class HomepageImageBanner(models.Model):
    """Image-only banner for an admin-maintained horizontal homepage carousel."""
    image = models.ImageField(upload_to="homepage/image-banners/")
    alt_text = models.CharField(max_length=180, help_text="Describe the banner image for accessibility.")
    target_url = models.CharField(max_length=500, blank=True, validators=[validate_homepage_link])
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Homepage image-only banner"
        verbose_name_plural = "Homepage image-only banners"

    def __str__(self):
        return self.alt_text
