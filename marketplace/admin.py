from django.contrib import admin
from django import forms
from django.urls import reverse
from django.utils.html import format_html
from .models import (
    MedicineCategory, MedicineProduct, Pharmacy, PharmacyListing, Prescription,
    CartItem, MarketplaceOrder, MarketplaceOrderItem, OrderStatusEvent, MarketplaceAuditLog,
    HomepagePromotion, HomepageTrustMetric, HomepageTestimonial, HomepageSearchTerm, HomepageEditorialSection,
    FooterSocialLink, HomepageSectionSetting, HomepageCategoryTile, HomepageShowcaseProduct,
    HomepageMembershipBanner, HomepageImageBanner, MarketplacePaymentSettings,
    PharmacyCounterSale, PharmacyCounterSaleItem,
)


@admin.register(MedicineCategory)
class MedicineCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("active",)



@admin.register(MedicineProduct)
class MedicineProductAdmin(admin.ModelAdmin):
    list_display = (
        "brand_name",
        "generic_name",
        "strength",
        "dosage_form",
        "category",
        "requires_prescription",
        "active",
    )

    list_editable = ("dosage_form",)

    search_fields = ("brand_name", "generic_name", "manufacturer")

    fields = (
        "brand_name",
        "generic_name",
        "strength",
        "dosage_form",
        "pack_size",
        "manufacturer",
        "category",
        "description",
        "image",
        "requires_prescription",
        "active",
    )

    list_filter = (
        "category",
        "dosage_form",
        "requires_prescription",
        "active",
    )


@admin.register(Pharmacy)
class PharmacyAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "city", "pincode", "verification_status", "offers_delivery", "offers_pickup")
    list_filter = ("verification_status", "city", "offers_delivery", "offers_pickup")
    search_fields = ("name", "owner__username", "licence_number", "pincode")
    readonly_fields = ("created_at", "updated_at", "verified_at")


@admin.register(PharmacyListing)
class PharmacyListingAdmin(admin.ModelAdmin):
    list_display = ("product", "pharmacy", "mrp", "selling_price", "available_quantity", "reserved_quantity", "expiry_date", "active", "last_stock_update")
    list_filter = ("active", "pharmacy__verification_status", "product__category")
    search_fields = ("product__brand_name", "product__generic_name", "pharmacy__name", "batch_number")
    readonly_fields = ("last_stock_update", "created_at", "updated_at")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "status", "callback_requested", "callback_phone", "preferred_pincode", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("status", "callback_requested", "created_at")
    search_fields = ("owner__username", "owner__email", "callback_phone", "requested_medicines", "preferred_pincode")
    readonly_fields = ("created_at", "reviewed_at", "callback_requested_at")


class MarketplaceOrderItemInline(admin.TabularInline):
    model = MarketplaceOrderItem
    extra = 0
    readonly_fields = ("product_name_snapshot", "quantity", "unit_price", "mrp_snapshot")


@admin.register(MarketplaceOrder)
class MarketplaceOrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "pharmacy", "status", "fulfilment", "payment_method", "payment_status", "total", "created_at")
    list_filter = ("status", "fulfilment", "payment_method", "payment_status", "created_at")
    search_fields = ("reference", "customer__username", "pharmacy__name", "gateway_payment_id", "payment_reference")
    exclude = ("payment_proof",)
    readonly_fields = (
        "reference", "subtotal", "delivery_fee", "total", "payment_collected_at", "payment_collected_by",
        "payment_method", "payment_status", "gateway_order_id", "gateway_payment_id", "payment_reference",
        "payment_review_note", "payment_verified_at", "payment_verified_by", "payment_proof_download_link",
        "created_at", "updated_at",
    )
    inlines = (MarketplaceOrderItemInline,)

    @admin.display(description="Payment proof / order review")
    def payment_proof_download_link(self, obj):
        if not obj or not obj.payment_proof:
            return "No proof uploaded"
        url = reverse("order_detail", kwargs={"reference": obj.reference})
        return format_html('<a href="{}">Open order details</a>', url)


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("customer", "listing", "quantity", "added_at")
    search_fields = ("customer__username", "listing__product__brand_name")


@admin.register(OrderStatusEvent)
class OrderStatusEventAdmin(admin.ModelAdmin):
    list_display = ("order", "actor", "old_status", "new_status", "created_at")
    list_filter = ("new_status", "created_at")
    readonly_fields = ("order", "actor", "old_status", "new_status", "note", "created_at")


@admin.register(MarketplaceAuditLog)
class MarketplaceAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "object_type", "object_id")
    list_filter = ("action", "created_at")
    search_fields = ("actor__username", "object_type", "object_id", "details")
    readonly_fields = ("actor", "action", "object_type", "object_id", "details", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SuperuserOnlyModelAdmin(admin.ModelAdmin):
    """Homepage content may only be managed by Django superusers."""
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


class HomepagePromotionAdminForm(forms.ModelForm):
    """Image-first offer editor; legacy copy fields stay out of the workflow."""
    class Meta:
        model = HomepagePromotion
        fields = ("image", "target_url")
        widgets = {
            "target_url": forms.TextInput(attrs={"placeholder": "/medicines/ or https://example.com/offer"}),
        }

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.title:
            obj.title = "Featured offer"
        if not obj.alt_text:
            obj.alt_text = "MedMitra featured offer"
        # Offers now render as image-only clickable cards. Old text is cleared so
        # it cannot unexpectedly reappear if another template reads these fields.
        obj.subtitle = ""
        obj.button_label = ""
        if commit:
            obj.save()
            self.save_m2m()
        return obj


@admin.register(HomepagePromotion)
class HomepagePromotionAdmin(SuperuserOnlyModelAdmin):
    form = HomepagePromotionAdminForm
    list_display = ("title", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "target_url")
    list_editable = ("is_active", "sort_order")
    fields = ("image", "target_url")
    def save_model(self, request, obj, form, change):
        if not obj.title:
            obj.title = "Featured offer"
        if not obj.alt_text:
            obj.alt_text = "MedMitra featured offer"
        obj.subtitle = ""
        obj.button_label = ""
        super().save_model(request, obj, form, change)


@admin.register(HomepageTrustMetric)
class HomepageTrustMetricAdmin(SuperuserOnlyModelAdmin):
    list_display = ("value", "label", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("value", "label", "detail")
    list_editable = ("is_active", "sort_order")


@admin.register(HomepageTestimonial)
class HomepageTestimonialAdmin(SuperuserOnlyModelAdmin):
    list_display = ("customer_name", "rating", "review_date", "is_published", "sort_order")
    list_filter = ("is_published", "rating")
    search_fields = ("customer_name", "location_label", "quote")
    list_editable = ("is_published", "sort_order")
    readonly_fields = ("created_at",)
    fieldsets = (
        ("Review", {"fields": ("customer_name", "location_label", "review_date", "rating", "quote")}),
        ("Publishing", {"fields": ("is_published", "sort_order")}),
        ("Audit", {"fields": ("created_at",)}),
    )


@admin.register(HomepageSearchTerm)
class HomepageSearchTermAdmin(SuperuserOnlyModelAdmin):
    list_display = ("term", "section", "target_url", "is_active", "sort_order")
    list_filter = ("section", "is_active")
    search_fields = ("term", "target_url")
    list_editable = ("is_active", "sort_order")
    fieldsets = (
        ("Search chip", {"fields": ("term", "section", "target_url")}),
        ("Display order", {"fields": ("is_active", "sort_order")}),
    )


@admin.register(HomepageEditorialSection)
class HomepageEditorialSectionAdmin(SuperuserOnlyModelAdmin):
    list_display = ("title", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "body", "seo_description")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Content", {"fields": ("eyebrow", "title", "body", "button_label", "button_url")}),
        ("SEO and publishing", {"fields": ("seo_description", "is_active", "sort_order")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

@admin.register(FooterSocialLink)
class FooterSocialLinkAdmin(SuperuserOnlyModelAdmin):
    list_display = ("platform", "label", "url", "is_active", "sort_order", "updated_at")
    list_filter = ("platform", "is_active", "open_in_new_tab")
    search_fields = ("platform", "label", "url")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Social profile", {"fields": ("platform", "label", "url", "open_in_new_tab")}),
        ("Footer display", {"fields": ("is_active", "sort_order")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )



@admin.register(HomepageSectionSetting)
class HomepageSectionSettingAdmin(SuperuserOnlyModelAdmin):
    list_display = ("key", "eyebrow", "title", "is_active", "sort_order", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and "key" not in fields:
            fields.append("key")
        return tuple(fields)
    list_filter = ("is_active", "key")
    search_fields = ("title", "eyebrow", "description")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("updated_at",)
    fieldsets = (
        ("Section heading", {"fields": ("key", "eyebrow", "title", "description")}),
        ("Visibility", {"fields": ("is_active", "sort_order")}),
        ("Audit", {"fields": ("updated_at",)}),
    )


@admin.register(HomepageCategoryTile)
class HomepageCategoryTileAdmin(SuperuserOnlyModelAdmin):
    list_display = ("name", "icon", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "subtitle")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Category content", {"fields": ("name", "subtitle", "icon", "image", "target_url")}),
        ("Display", {"fields": ("is_active", "sort_order")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
class HomepageShowcaseProductAdminForm(forms.ModelForm):
    # A product name can be filled automatically from a selection.
    name = forms.CharField(required=False)

    class Meta:
        model = HomepageShowcaseProduct
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()

        source = cleaned.get("source_type")
        catalogue = cleaned.get("catalogue_product")
        listing = cleaned.get("inventory_listing")

        if source == "catalogue":
            if not catalogue:
                self.add_error(
                    "catalogue_product",
                    "Select a medicine from the catalogue.",
                )
            else:
                cleaned["name"] = catalogue.brand_name
                parts = [
                    catalogue.generic_name,
                    catalogue.strength,
                    catalogue.pack_size,
                ]
                cleaned["subtitle"] = " · ".join(
                    str(part).strip()
                    for part in parts
                    if part and str(part).strip()
                )

        elif source == "inventory":
            if not listing:
                self.add_error(
                    "inventory_listing",
                    "Select a pharmacy inventory listing.",
                )
            else:
                product = listing.product
                cleaned["name"] = product.brand_name

                parts = [
                    product.generic_name,
                    product.strength,
                    product.pack_size,
                    listing.pharmacy.name,
                ]
                cleaned["subtitle"] = " · ".join(
                    str(part).strip()
                    for part in parts
                    if part and str(part).strip()
                )

                # Copy the selected listing's prices when saving.
                cleaned["mrp"] = listing.mrp
                cleaned["price"] = listing.selling_price
                cleaned["is_sample"] = False

        elif not (cleaned.get("name") or "").strip():
            self.add_error("name", "Enter a product name.")

        return cleaned

@admin.register(HomepageShowcaseProduct)
class HomepageShowcaseProductAdmin(SuperuserOnlyModelAdmin):
    form = HomepageShowcaseProductAdminForm

    list_display = (
        "name",
        "section",
        "mrp",
        "price",
        "is_sample",
        "is_active",
        "sort_order",
    )

    list_filter = ("section", "is_sample", "is_active")
    search_fields = ("name", "subtitle")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("created_at", "updated_at")

    autocomplete_fields = (
        "catalogue_product",
        "inventory_listing",
    )

    fieldsets = (
        (
            "Product card",
            {
                "fields": (
                    "section",
                    "source_type",
                    "catalogue_product",
                    "inventory_listing",
                    "name",
                    "subtitle",
                    "image",
                    "target_url",
                )
            },
        ),
        (
            "Price display",
            {"fields": ("mrp", "price", "is_sample")},
        ),
        (
            "Publishing",
            {"fields": ("is_active", "sort_order")},
        ),
        (
            "Audit",
            {"fields": ("created_at", "updated_at")},
        ),
    )


@admin.register(HomepageMembershipBanner)
class HomepageMembershipBannerAdmin(SuperuserOnlyModelAdmin):
    list_display = ("title", "button_label", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "eyebrow", "description")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Wide membership banner", {"fields": ("eyebrow", "title", "description", "button_label", "button_url", "image")}),
        ("Publishing", {"fields": ("is_active", "sort_order")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(HomepageImageBanner)
class HomepageImageBannerAdmin(SuperuserOnlyModelAdmin):
    list_display = ("alt_text", "is_active", "sort_order", "starts_at", "ends_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("alt_text", "target_url")
    list_editable = ("is_active", "sort_order")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Image-only banner", {"fields": ("image", "alt_text", "target_url")}),
        ("Display and scheduling", {"fields": ("is_active", "sort_order", "starts_at", "ends_at")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(MarketplacePaymentSettings)
class MarketplacePaymentSettingsAdmin(SuperuserOnlyModelAdmin):
    list_display = ("display_name", "upi_id", "is_active", "updated_at")
    list_filter = ("is_active",)
    readonly_fields = ("updated_at",)
    fields = ("display_name", "upi_id", "qr_image", "instructions", "is_active", "updated_at")

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not MarketplacePaymentSettings.objects.exists()


class PharmacyCounterSaleItemInline(admin.TabularInline):
    model = PharmacyCounterSaleItem
    extra = 0
    can_delete = False
    readonly_fields = ("listing", "product_name_snapshot", "quantity", "unit_price")


@admin.register(PharmacyCounterSale)
class PharmacyCounterSaleAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "pharmacy", "customer_name", "total", "payment_method", "created_by", "created_at")
    list_filter = ("payment_method", "created_at", "pharmacy")
    search_fields = ("receipt_number", "customer_name", "pharmacy__name", "created_by__username")
    readonly_fields = ("receipt_number", "public_token", "customer_name", "created_by", "payment_method", "total", "created_at")
    inlines = (PharmacyCounterSaleItemInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
