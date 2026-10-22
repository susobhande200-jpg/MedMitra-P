from decimal import Decimal, InvalidOperation
from datetime import timedelta
import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
import re
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Count, F, DecimalField, ExpressionWrapper
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import PharmacyRegistrationForm, PharmacyPaymentDetailsForm, ListingForm, PrescriptionUploadForm, CartAddForm, CheckoutForm, PaymentProofForm
from .models import (
    MedicineCategory, MedicineProduct, Pharmacy, PharmacyListing, Prescription,
    CartItem, MarketplaceOrder, MarketplaceOrderItem, OrderStatusEvent, MarketplaceAuditLog,
    HomepagePromotion, HomepageTrustMetric, HomepageTestimonial, HomepageSearchTerm, HomepageEditorialSection,
    HomepageSectionSetting, HomepageCategoryTile, HomepageShowcaseProduct, HomepageMembershipBanner, HomepageImageBanner, MarketplacePaymentSettings,
    PharmacyCounterSale, PharmacyCounterSaleItem,
)


logger = logging.getLogger(__name__)


def _write_audit(actor, action, obj, details=""):
    """Record sensitive marketplace actions without logging health-document contents."""
    MarketplaceAuditLog.objects.create(
        actor=actor, action=action, object_type=obj._meta.label_lower,
        object_id=str(obj.pk), details=str(details)[:500],
    )


def _payment_qr_settings_for_pharmacy(pharmacy):
    """Return the selected store's payee details, falling back to legacy admin QR config."""
    if pharmacy and pharmacy.has_payment_destination:
        return {
            "display_name": pharmacy.name,
            "qr_image": pharmacy.payment_qr_image,
            "upi_id": pharmacy.upi_id,
            "bank_account_name": pharmacy.bank_account_name,
            "bank_name": pharmacy.bank_name,
            "bank_account_number": pharmacy.bank_account_number,
            "bank_ifsc_code": pharmacy.bank_ifsc_code,
            "instructions": pharmacy.payment_instructions or "Pay the exact order total and upload your transaction proof.",
        }
    global_settings = MarketplacePaymentSettings.active_qr()
    if global_settings:
        return {
            "display_name": global_settings.display_name,
            "qr_image": global_settings.qr_image,
            "upi_id": global_settings.upi_id,
            "bank_account_name": "", "bank_name": "", "bank_account_number": "", "bank_ifsc_code": "",
            "instructions": global_settings.instructions,
        }
    return None


def _public_listings():
    return PharmacyListing.objects.filter(
        active=True,
        pharmacy__verification_status=Pharmacy.VerificationStatus.APPROVED,
        product__active=True,
    ).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.localdate())).select_related("product", "product__category", "pharmacy")


def home(request):
    now = timezone.now()
    featured = _public_listings().filter(available_quantity__gt=F("reserved_quantity")).order_by("-last_stock_update")[:8]

    promotions = HomepagePromotion.objects.filter(is_active=True).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
    ).order_by("sort_order", "id")
    metrics = HomepageTrustMetric.objects.filter(is_active=True).order_by("sort_order", "id")
    testimonials = HomepageTestimonial.objects.filter(is_published=True).order_by("sort_order", "-review_date", "id")
    search_terms = HomepageSearchTerm.objects.filter(is_active=True).order_by("sort_order", "term")
    editorial_sections = HomepageEditorialSection.objects.filter(is_active=True).order_by("sort_order", "id")
    homepage_meta_description = editorial_sections.exclude(seo_description="").values_list("seo_description", flat=True).first()
    section_settings = {item.key: item for item in HomepageSectionSetting.objects.all()}
    image_banners = HomepageImageBanner.objects.filter(is_active=True).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
    ).order_by("sort_order", "id")

    return render(request, "marketplace/home.html", {
        "featured": featured,
        "categories": MedicineCategory.objects.filter(active=True)[:8],
        "pharmacy_count": Pharmacy.objects.filter(verification_status=Pharmacy.VerificationStatus.APPROVED).count(),
        "product_count": MedicineProduct.objects.filter(active=True).count(),
        "homepage_promotions": promotions,
        "homepage_metrics": metrics,
        "homepage_testimonials": testimonials,
        "top_healthcare_terms": search_terms.filter(section=HomepageSearchTerm.Section.HEALTHCARE),
        "top_medicine_terms": search_terms.filter(section=HomepageSearchTerm.Section.MEDICINES),
        "top_searched_terms": search_terms.filter(section=HomepageSearchTerm.Section.SEARCHED),
        "top_vaccine_terms": search_terms.filter(section=HomepageSearchTerm.Section.VACCINES),
        "top_selling_terms": search_terms.filter(section=HomepageSearchTerm.Section.TOP_SELLING),
        "trending_terms": search_terms.filter(section=HomepageSearchTerm.Section.TRENDING),
        "discount_terms": search_terms.filter(section=HomepageSearchTerm.Section.DISCOUNTS),
        "homepage_editorial_sections": editorial_sections,
        "homepage_meta_description": homepage_meta_description,
        "homepage_section_settings": section_settings,
        "homepage_categories": HomepageCategoryTile.objects.filter(is_active=True),
        "homepage_new_launches": HomepageShowcaseProduct.objects.filter(section=HomepageShowcaseProduct.Section.NEW_LAUNCHES, is_active=True),
        "homepage_trending_products": HomepageShowcaseProduct.objects.filter(section=HomepageShowcaseProduct.Section.TRENDING, is_active=True),
        "homepage_membership_banners": HomepageMembershipBanner.objects.filter(is_active=True),
        "homepage_image_banners": image_banners,
    })


def medicine_search(request):
    listings = _public_listings().filter(available_quantity__gt=F("reserved_quantity"))
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    pincode = request.GET.get("pincode", "").strip()
    fulfilment = request.GET.get("fulfilment", "").strip()
    sort = request.GET.get("sort", "relevance").strip()
    if q:
        listings = listings.filter(
            Q(product__brand_name__icontains=q)
            | Q(product__generic_name__icontains=q)
            | Q(product__strength__icontains=q)
            | Q(product__manufacturer__icontains=q)
        )
    if category:
        listings = listings.filter(product__category__slug=category)
    if pincode:
        listings = listings.filter(pharmacy__pincode__icontains=pincode)
    if fulfilment == "delivery":
        listings = listings.filter(pharmacy__offers_delivery=True)
    elif fulfilment == "pickup":
        listings = listings.filter(pharmacy__offers_pickup=True)
    if sort == "price_low":
        listings = listings.order_by("selling_price", "product__brand_name")
    elif sort == "discount":
        listings = listings.annotate(discount_value=ExpressionWrapper(100 * (F("mrp") - F("selling_price")) / F("mrp"), output_field=DecimalField(max_digits=7, decimal_places=2))).order_by("-discount_value", "selling_price")
    else:
        listings = listings.order_by("product__brand_name", "selling_price")
    return render(request, "marketplace/medicine_search.html", {
        "listings": listings[:100], "q": q, "categories": MedicineCategory.objects.filter(active=True),
        "selected_category": category, "pincode": pincode, "fulfilment": fulfilment, "sort": sort,
        "result_count": listings.count(),
    })


def medicine_detail(request, pk):
    product = get_object_or_404(MedicineProduct, pk=pk, active=True)
    pincode = request.GET.get("pincode", "").strip()
    fulfilment = request.GET.get("fulfilment", "").strip()
    sort = request.GET.get("sort", "price_low").strip()
    listings = _public_listings().filter(product=product, available_quantity__gt=F("reserved_quantity"))
    if pincode:
        listings = listings.filter(pharmacy__pincode__startswith=pincode)
    if fulfilment == "delivery":
        listings = listings.filter(pharmacy__offers_delivery=True)
    elif fulfilment == "pickup":
        listings = listings.filter(pharmacy__offers_pickup=True)
    if sort == "discount":
        listings = listings.annotate(discount_value=ExpressionWrapper(100 * (F("mrp") - F("selling_price")) / F("mrp"), output_field=DecimalField(max_digits=7, decimal_places=2))).order_by("-discount_value", "selling_price")
    elif sort == "recent":
        listings = listings.order_by("-last_stock_update", "selling_price")
    else:
        listings = listings.order_by("selling_price", "pharmacy__name")
    # Prefer an actual pharmacy photo when the shared catalogue has no image.
    listing_image = listings.exclude(image="").first()
    return render(request, "marketplace/medicine_detail.html", {
        "product": product, "listings": listings, "listing_image": listing_image, "pincode": pincode,
        "fulfilment": fulfilment, "sort": sort,
    })


def pharmacy_finder(request):
    pharmacies = Pharmacy.objects.filter(verification_status=Pharmacy.VerificationStatus.APPROVED).annotate(
        live_listings=Count(
            "listings",
            filter=Q(
                listings__active=True, listings__available_quantity__gt=F("listings__reserved_quantity"),
                listings__product__active=True,
            ) & (Q(listings__expiry_date__isnull=True) | Q(listings__expiry_date__gte=timezone.localdate())),
            distinct=True,
        ),
    )
    q = request.GET.get("q", "").strip()
    pincode = request.GET.get("pincode", "").strip()
    delivery = request.GET.get("delivery", "")
    if q:
        pharmacies = pharmacies.filter(Q(name__icontains=q) | Q(city__icontains=q) | Q(locality__icontains=q) | Q(address__icontains=q))
    if pincode:
        pharmacies = pharmacies.filter(pincode__icontains=pincode)
    if delivery == "yes":
        pharmacies = pharmacies.filter(offers_delivery=True)
    pharmacies = pharmacies.order_by("city", "name")
    map_points = []
    for p in pharmacies:
        if p.latitude is not None and p.longitude is not None:
            map_points.append({"name": p.name, "lat": float(p.latitude), "lng": float(p.longitude), "address": p.full_address, "url": f"/pharmacies/{p.slug}/"})
    return render(request, "marketplace/pharmacy_finder.html", {
        "pharmacies": pharmacies, "q": q, "pincode": pincode, "delivery": delivery,
        "map_points": map_points,
    })


def pharmacy_detail(request, slug):
    pharmacy = get_object_or_404(Pharmacy, slug=slug, verification_status=Pharmacy.VerificationStatus.APPROVED)
    listings = _public_listings().filter(pharmacy=pharmacy).order_by("product__brand_name")
    return render(request, "marketplace/pharmacy_detail.html", {"pharmacy": pharmacy, "listings": listings})


@login_required
def retailer_register(request):
    if request.method == "POST":
        form = PharmacyRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            pharmacy = form.save(commit=False)
            pharmacy.owner = request.user
            pharmacy.verification_status = Pharmacy.VerificationStatus.PENDING
            pharmacy.save()
            _write_audit(request.user, "pharmacy_submitted", pharmacy, "Submitted for verification")
            messages.success(request, "Pharmacy profile submitted. It will appear in public search after administrator verification.")
            return redirect("retailer_dashboard")
    else:
        form = PharmacyRegistrationForm()
    return render(request, "marketplace/retailer_register.html", {"form": form})


def _owned_pharmacy(request, pharmacy_id=None):
    qs = Pharmacy.objects.filter(owner=request.user).order_by("created_at")
    if request.user.is_staff or request.user.is_superuser:
        qs = Pharmacy.objects.all().order_by("created_at")
    if pharmacy_id:
        return get_object_or_404(qs, pk=pharmacy_id)
    return qs.first()


@login_required
def retailer_payment_settings(request):
    """Let a pharmacy owner configure or update the QR/UPI/bank destination for their store."""
    pharmacy = _owned_pharmacy(request, request.GET.get("pharmacy") or request.POST.get("pharmacy_id"))
    if pharmacy is None:
        messages.info(request, "Register your pharmacy before configuring payment details.")
        return redirect("retailer_register")
    if not _is_pharmacy_owner(request.user, pharmacy):
        raise PermissionDenied
    if pharmacy.verification_status in {Pharmacy.VerificationStatus.REJECTED, Pharmacy.VerificationStatus.SUSPENDED}:
        messages.error(request, "Payment settings cannot be changed while this pharmacy is rejected or suspended.")
        return redirect("retailer_dashboard")
    if request.method == "POST":
        form = PharmacyPaymentDetailsForm(request.POST, request.FILES, instance=pharmacy)
        if form.is_valid():
            saved = form.save()
            _write_audit(request.user, "pharmacy_payment_details_updated", saved, f"Pharmacy #{saved.pk}; destination configured={saved.has_payment_destination}")
            messages.success(request, "Store payment details saved. Customers can use these details for new QR payment submissions.")
            return redirect(f"/retailer/?pharmacy={pharmacy.pk}")
    else:
        form = PharmacyPaymentDetailsForm(instance=pharmacy)
    return render(request, "marketplace/retailer_payment_settings.html", {"pharmacy": pharmacy, "form": form})


@login_required
def retailer_dashboard(request):
    pharmacies = Pharmacy.objects.filter(owner=request.user).order_by("created_at")
    if request.user.is_staff or request.user.is_superuser:
        pharmacies = Pharmacy.objects.all().order_by("created_at")
    if not pharmacies.exists():
        return render(request, "marketplace/retailer_dashboard.html", {"pharmacies": pharmacies, "pharmacy": None})
    pharmacy = _owned_pharmacy(request, request.GET.get("pharmacy"))
    listings = PharmacyListing.objects.filter(pharmacy=pharmacy).select_related("product")
    orders = MarketplaceOrder.objects.filter(pharmacy=pharmacy).select_related("customer")[:8]
    today = timezone.localdate()
    context = {
        "pharmacies": pharmacies, "pharmacy": pharmacy, "listings": listings,
        "listing_count": listings.count(),
        "low_stock_count": listings.filter(active=True, available_quantity__gt=F("reserved_quantity"), available_quantity__lte=F("reserved_quantity") + 5).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)).count(),
        "out_of_stock_count": listings.filter(available_quantity__lte=F("reserved_quantity"), active=True).count(),
        "near_expiry_count": listings.filter(active=True, available_quantity__gt=F("reserved_quantity"), expiry_date__gte=today, expiry_date__lte=today + timedelta(days=60)).count(),
        "expired_stock_count": listings.filter(active=True, available_quantity__gt=F("reserved_quantity"), expiry_date__lt=today).count(),
        "pending_orders": MarketplaceOrder.objects.filter(pharmacy=pharmacy, status=MarketplaceOrder.Status.PENDING).count(),
        "orders": orders,
    }
    return render(request, "marketplace/retailer_dashboard.html", context)


@login_required
def retailer_listings(request):
    pharmacy = _owned_pharmacy(request, request.GET.get("pharmacy"))
    if pharmacy is None:
        messages.info(request, "Register your pharmacy to manage inventory.")
        return redirect("retailer_register")
    listings = PharmacyListing.objects.filter(pharmacy=pharmacy).select_related("product", "product__category").order_by("product__brand_name")
    q = request.GET.get("q", "").strip()
    if q:
        listings = listings.filter(Q(product__brand_name__icontains=q) | Q(product__generic_name__icontains=q))
    stock_filter = request.GET.get("stock", "").strip()
    today = timezone.localdate()
    if stock_filter == "low":
        listings = listings.filter(active=True, available_quantity__gt=F("reserved_quantity"), available_quantity__lte=F("reserved_quantity") + 5).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
    elif stock_filter == "out":
        listings = listings.filter(active=True, available_quantity__lte=F("reserved_quantity"))
    elif stock_filter == "near_expiry":
        listings = listings.filter(active=True, available_quantity__gt=F("reserved_quantity"), expiry_date__gte=today, expiry_date__lte=today + timedelta(days=60))
    elif stock_filter == "expired":
        listings = listings.filter(active=True, available_quantity__gt=F("reserved_quantity"), expiry_date__lt=today)
    return render(request, "marketplace/retailer_listings.html", {"pharmacy": pharmacy, "listings": listings, "q": q, "stock_filter": stock_filter})


@login_required
def retailer_listing_form(request, pk=None):
    if pk:
        listing = get_object_or_404(PharmacyListing, pk=pk)
        if listing.pharmacy.owner_id != request.user.id and not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied
        pharmacy = listing.pharmacy
    else:
        pharmacy = _owned_pharmacy(request, request.GET.get("pharmacy"))
        listing = None
        if pharmacy is None:
            messages.info(request, "Register your pharmacy first.")
            return redirect("retailer_register")
        if pharmacy.verification_status in {Pharmacy.VerificationStatus.REJECTED, Pharmacy.VerificationStatus.SUSPENDED}:
            messages.error(request, "This pharmacy cannot edit marketplace inventory while its verification is rejected or suspended. Contact the administrator for review.")
            return redirect("retailer_dashboard")
        # Pending stores may prepare inventory in advance. Public search remains
        # gated by Pharmacy.VerificationStatus.APPROVED in _public_listings().
    if request.method == "POST":
        form = ListingForm(request.POST, request.FILES, instance=listing)
        if form.is_valid():
            with transaction.atomic():
                saved = form.save(commit=False)
                if form.cleaned_data.get("new_catalogue_product"):
                    product_image = form.cleaned_data.get("new_product_image")
                    product = MedicineProduct.objects.create(
                        brand_name=form.cleaned_data["new_product_name"].strip(),
                        generic_name=(form.cleaned_data.get("new_generic_name") or "").strip(),
                        strength=(form.cleaned_data.get("new_strength") or "").strip(),
                        dosage_form=form.cleaned_data["new_dosage_form"],
                        pack_size=(form.cleaned_data.get("new_pack_size") or "").strip(),
                        manufacturer=(form.cleaned_data.get("new_manufacturer") or "").strip(),
                        category=form.cleaned_data.get("new_category"),
                        requires_prescription=bool(form.cleaned_data.get("new_requires_prescription")),
                        active=True,
                        description=f"Added to the MedMitra catalogue by a pharmacy listing for {pharmacy.name}.",
                    )
                    if product_image:
                        product.image = product_image
                        product.save(update_fields=["image"])
                    saved.product = product
                saved.pharmacy = pharmacy
                saved.save()
                _write_audit(request.user, "listing_saved", saved, f"Pharmacy #{pharmacy.pk}; product #{saved.product_id}; active={saved.active}")
            if not pharmacy.verified:
                messages.success(request, "Medicine saved to your draft inventory. It stays hidden from customers until an administrator approves your pharmacy.")
            else:
                messages.success(request, "Medicine listing saved.")
            return redirect(f"/retailer/listings/?pharmacy={pharmacy.pk}")
    else:
        form = ListingForm(instance=listing)
    return render(request, "marketplace/listing_form.html", {"form": form, "pharmacy": pharmacy, "listing": listing})


@login_required
def retailer_orders(request):
    pharmacies = Pharmacy.objects.filter(owner=request.user)
    if request.user.is_staff or request.user.is_superuser:
        pharmacies = Pharmacy.objects.all()
    selected_pharmacy = None
    pharmacy_id = request.GET.get("pharmacy", "").strip()
    if pharmacy_id:
        selected_pharmacy = get_object_or_404(pharmacies, pk=pharmacy_id)
    orders = MarketplaceOrder.objects.filter(pharmacy__in=pharmacies).select_related("customer", "pharmacy").prefetch_related("items")
    if selected_pharmacy:
        orders = orders.filter(pharmacy=selected_pharmacy)
    status = request.GET.get("status", "").strip()
    if status in MarketplaceOrder.Status.values:
        orders = orders.filter(status=status)
    return render(request, "marketplace/retailer_orders.html", {
        "orders": orders[:150], "status": status, "statuses": MarketplaceOrder.Status.choices,
        "pharmacies": pharmacies, "selected_pharmacy": selected_pharmacy or pharmacies.first(),
    })


@login_required
def retailer_counter_sale(request):
    """Create an offline walk-in sale using this shop's marketplace listings."""
    pharmacy_id = (request.POST.get("pharmacy_id") or request.GET.get("pharmacy") or "").strip()
    pharmacy = _owned_pharmacy(request, pharmacy_id or None)
    if pharmacy is None:
        messages.info(request, "Register your pharmacy before creating a counter sale.")
        return redirect("retailer_register")
    if not _is_pharmacy_owner(request.user, pharmacy):
        raise PermissionDenied
    if pharmacy.verification_status != Pharmacy.VerificationStatus.APPROVED and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Counter sales are available after the pharmacy has been verified.")
        return redirect("retailer_dashboard")

    today = timezone.localdate()
    listings = PharmacyListing.objects.filter(
        pharmacy=pharmacy, active=True, product__active=True,
        available_quantity__gt=F("reserved_quantity"),
    ).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)).select_related("product").order_by("product__brand_name", "product__strength")
    if request.method == "POST":
        listing_ids = request.POST.getlist("listing_id")
        quantities = request.POST.getlist("quantity")
        customer_name = request.POST.get("customer_name", "").strip()[:160]
        payment_method = request.POST.get("payment_method", PharmacyCounterSale.PaymentMethod.CASH)
        errors = []
        if payment_method not in PharmacyCounterSale.PaymentMethod.values:
            errors.append("Choose Cash, UPI, or Card as the payment method.")
        if not listing_ids or len(listing_ids) != len(quantities) or len(listing_ids) > 30:
            errors.append("Add one to 30 medicine rows, each with a quantity.")
        requested = {}
        for listing_id, qty_value in zip(listing_ids, quantities):
            if not listing_id:
                continue
            try:
                lid = int(listing_id)
                qty = int(qty_value)
            except (TypeError, ValueError):
                errors.append("Select a valid medicine and quantity in every row.")
                continue
            if qty < 1 or qty > 9999:
                errors.append("Each quantity must be between 1 and 9,999.")
                continue
            requested[lid] = requested.get(lid, 0) + qty
        if not requested:
            errors.append("Choose at least one medicine from this pharmacy's active listings.")

        sale = None
        if not errors:
            try:
                with transaction.atomic():
                    locked_listings = {}
                    for listing_id in sorted(requested):
                        try:
                            listing = PharmacyListing.objects.select_for_update().select_related("product", "pharmacy").get(
                                pk=listing_id, pharmacy=pharmacy, active=True, product__active=True
                            )
                        except PharmacyListing.DoesNotExist:
                            raise ValidationError("A selected medicine no longer belongs to this pharmacy or is inactive. Refresh and try again.")
                        if listing.is_expired or (listing.expiry_date and listing.expiry_date < today):
                            raise ValidationError(f"{listing.product.brand_name} is expired and cannot be sold.")
                        if requested[listing_id] > listing.sellable_quantity:
                            raise ValidationError(f"Not enough unreserved stock for {listing.product.brand_name}. Available for counter sale: {listing.sellable_quantity}.")
                        locked_listings[listing_id] = listing
                    sale = PharmacyCounterSale.objects.create(
                        pharmacy=pharmacy,
                        receipt_number=f"POS-{timezone.localtime():%y%m%d}-{uuid.uuid4().hex[:6].upper()}",
                        customer_name=customer_name, created_by=request.user, payment_method=payment_method,
                    )
                    total = Decimal("0.00")
                    for listing_id, qty in requested.items():
                        listing = locked_listings[listing_id]
                        line_total = listing.selling_price * qty
                        PharmacyCounterSaleItem.objects.create(
                            sale=sale, listing=listing, product_name_snapshot=str(listing.product),
                            quantity=qty, unit_price=listing.selling_price,
                        )
                        total += line_total
                        listing.available_quantity -= qty
                        listing.save(update_fields=["available_quantity", "last_stock_update", "updated_at"])
                    sale.total = total
                    sale.save(update_fields=["total"])
                    _write_audit(request.user, "counter_sale_created", sale, f"Pharmacy #{pharmacy.pk}; lines={len(requested)}; total={total}; payment={payment_method}")
            except ValidationError as exc:
                errors.extend(getattr(exc, "messages", [str(exc)]))
        if sale:
            messages.success(request, f"Counter sale recorded. Receipt {sale.receipt_number} is ready to print or share.")
            return redirect("counter_sale_receipt", token=sale.public_token)
        for error in errors:
            messages.error(request, error)

    return render(request, "marketplace/retailer_counter_sale.html", {
        "pharmacy": pharmacy, "listings": listings,
        "payment_methods": PharmacyCounterSale.PaymentMethod.choices,
    })


def counter_sale_receipt(request, token):
    """Read-only public receipt via unguessable UUID token; contains no account credentials."""
    sale = get_object_or_404(
        PharmacyCounterSale.objects.select_related("pharmacy", "created_by").prefetch_related("items"),
        public_token=token,
    )
    response = render(request, "marketplace/counter_sale_receipt.html", {"sale": sale})
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _is_pharmacy_owner(user, pharmacy):
    return bool(user.is_staff or user.is_superuser or pharmacy.owner_id == user.id)


def _release_order_reservations(order, consume=False):
    for item in order.items.select_related("listing").all():
        listing = PharmacyListing.objects.select_for_update().get(pk=item.listing_id)
        listing.reserved_quantity = max(0, listing.reserved_quantity - item.quantity)
        if consume:
            listing.available_quantity = max(0, listing.available_quantity - item.quantity)
        listing.save(update_fields=["reserved_quantity", "available_quantity", "last_stock_update", "updated_at"])


def _transition_order(order, new_status, actor, note=""):
    old = order.status
    # If a paid online order must be rejected by the pharmacy, retain a visible
    # refund-pending state instead of incorrectly recording an ordinary rejection.
    if new_status in {MarketplaceOrder.Status.REJECTED, MarketplaceOrder.Status.CANCELLED} and order.payment_status == MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED:
        raise ValidationError("Payment proof has been submitted. Review the transfer before cancelling or rejecting this order.")
    if new_status in {MarketplaceOrder.Status.REJECTED, MarketplaceOrder.Status.CANCELLED} and order.payment_status == MarketplaceOrder.PaymentStatus.PAID:
        new_status = MarketplaceOrder.Status.REFUND_PENDING
        note = (note + " Paid online order cancelled/rejected; refund requires manual processing.").strip()
    allowed = {
        MarketplaceOrder.Status.PENDING: {MarketplaceOrder.Status.ACCEPTED, MarketplaceOrder.Status.REJECTED, MarketplaceOrder.Status.CANCELLED, MarketplaceOrder.Status.REFUND_PENDING},
        MarketplaceOrder.Status.ACCEPTED: {MarketplaceOrder.Status.PROCESSING, MarketplaceOrder.Status.CANCELLED, MarketplaceOrder.Status.REFUND_PENDING},
        MarketplaceOrder.Status.PROCESSING: {MarketplaceOrder.Status.READY, MarketplaceOrder.Status.OUT_FOR_DELIVERY, MarketplaceOrder.Status.CANCELLED, MarketplaceOrder.Status.REFUND_PENDING},
        MarketplaceOrder.Status.READY: {MarketplaceOrder.Status.COMPLETED, MarketplaceOrder.Status.CANCELLED, MarketplaceOrder.Status.REFUND_PENDING},
        MarketplaceOrder.Status.OUT_FOR_DELIVERY: {MarketplaceOrder.Status.COMPLETED, MarketplaceOrder.Status.REFUND_PENDING},
        MarketplaceOrder.Status.REFUND_PENDING: {MarketplaceOrder.Status.REFUNDED},
    }
    if new_status not in allowed.get(old, set()):
        new_label = dict(MarketplaceOrder.Status.choices).get(new_status, "that status")
        raise ValidationError(f"Cannot change an order from {order.get_status_display()} to {new_label}.")
    if new_status == MarketplaceOrder.Status.ACCEPTED:
        if order.payment_method in {MarketplaceOrder.PaymentMethod.RAZORPAY, MarketplaceOrder.PaymentMethod.SBI_QR} and order.payment_status != MarketplaceOrder.PaymentStatus.PAID:
            raise ValidationError("Online payment must be verified before this order can be accepted.")
        if order.items.filter(listing__product__requires_prescription=True).exists():
            if not order.prescription or order.prescription.status != Prescription.Status.APPROVED:
                raise ValidationError("The linked prescription must be approved before this order can be accepted.")
        if order.items.filter(listing__expiry_date__lt=timezone.localdate()).exists():
            raise ValidationError("This order contains an expired batch and cannot be accepted.")
    if new_status == MarketplaceOrder.Status.COMPLETED:
        if order.items.filter(listing__expiry_date__lt=timezone.localdate()).exists():
            raise ValidationError("This order contains an expired batch and cannot be completed.")
        _release_order_reservations(order, consume=True)
    elif new_status in {MarketplaceOrder.Status.REJECTED, MarketplaceOrder.Status.CANCELLED, MarketplaceOrder.Status.REFUND_PENDING} and old in {
        MarketplaceOrder.Status.PENDING, MarketplaceOrder.Status.ACCEPTED, MarketplaceOrder.Status.PROCESSING,
        MarketplaceOrder.Status.READY, MarketplaceOrder.Status.OUT_FOR_DELIVERY,
    }:
        _release_order_reservations(order, consume=False)
    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    OrderStatusEvent.objects.create(order=order, actor=actor, old_status=old, new_status=new_status, note=note[:300])
    _write_audit(actor, "order_status_changed", order, f"{old} -> {new_status}")


@login_required
@require_POST
def retailer_order_status(request, pk):
    order = get_object_or_404(MarketplaceOrder.objects.select_related("pharmacy", "prescription"), pk=pk)
    if not _is_pharmacy_owner(request.user, order.pharmacy):
        raise PermissionDenied
    # Detail-page actions opt in to returning to the same order. The destination is
    # deliberately a named local route, never a user-supplied URL (open-redirect safe).
    return_to_detail = request.POST.get("return_to") == "detail"
    new_status = request.POST.get("status", "")
    if (
        new_status == MarketplaceOrder.Status.ACCEPTED
        and order.status == MarketplaceOrder.Status.PENDING
        and order.fulfilment == MarketplaceOrder.Fulfilment.PICKUP
        and order.payment_method == MarketplaceOrder.PaymentMethod.PAY_AT_STORE
        and bool(_payment_qr_settings_for_pharmacy(order.pharmacy))
        and order.payment_status != MarketplaceOrder.PaymentStatus.PAID
    ):
        messages.error(request, "This pharmacy accepts QR / bank-transfer payment for pickup. Ask the customer to upload payment proof and verify the transfer before accepting the order.")
        return redirect("order_detail", reference=order.reference) if return_to_detail else redirect("retailer_orders")
    try:
        with transaction.atomic():
            order = MarketplaceOrder.objects.select_for_update().get(pk=order.pk)
            _transition_order(order, new_status, request.user, request.POST.get("note", ""))
        messages.success(request, f"Order {order.reference} updated to {order.get_status_display()}.")
    except (ValidationError, ValueError) as exc:
        messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
    return redirect("order_detail", reference=order.reference) if return_to_detail else redirect("retailer_orders")


@login_required
@require_POST
def customer_cancel_order(request, pk):
    order = get_object_or_404(MarketplaceOrder.objects.select_related("pharmacy"), pk=pk)
    if order.customer_id != request.user.id:
        raise PermissionDenied
    if order.payment_status == MarketplaceOrder.PaymentStatus.PAID:
        messages.error(request, "This order has a verified online payment. Contact the pharmacy to request cancellation and a refund; no automatic refund has been issued.")
        return redirect("order_detail", reference=order.reference)
    if order.payment_status == MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED:
        messages.error(request, "Your payment proof is being reviewed. Contact the pharmacy before requesting cancellation so a possible transfer is not lost.")
        return redirect("order_detail", reference=order.reference)
    try:
        with transaction.atomic():
            order = MarketplaceOrder.objects.select_for_update().get(pk=order.pk)
            _transition_order(order, MarketplaceOrder.Status.CANCELLED, request.user, "Cancelled by customer")
        if order.status == MarketplaceOrder.Status.REFUND_PENDING:
            messages.warning(request, "A captured payment was confirmed while cancellation was processing. The order is now marked refund pending; contact support for manual refund handling.")
        else:
            messages.success(request, f"Order {order.reference} cancelled. The stock reservation was released.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("order_detail", reference=order.reference)


@login_required
def customer_dashboard(request):
    orders = MarketplaceOrder.objects.filter(customer=request.user).select_related("pharmacy", "prescription").prefetch_related("items")
    prescriptions = Prescription.objects.filter(owner=request.user)
    return render(request, "marketplace/customer_dashboard.html", {"orders": orders[:100], "prescriptions": prescriptions[:10]})


def _prescription_pharmacy_matches(prescription):
    """Return local pharmacies listing every manually entered medicine name.

    This uses only the customer's typed list. Prescription-file OCR is intentionally
    not implied; an authorized pharmacy must still verify the document and stock.
    """
    terms = [line.strip() for line in re.split(r"[\n;]+", prescription.requested_medicines or "") if line.strip()][:20]
    if not terms:
        return []

    # Customers may paste catalogue titles such as "Brand | flavour | pack size".
    # Match the first title segment and ignore common packaging words rather than requiring
    # every marketing descriptor to be identical to the store's medicine record.
    ignored_words = {
        "of", "the", "and", "for", "with", "from", "strip", "strips", "tablet", "tablets",
        "capsule", "capsules", "bottle", "box", "pack", "unit", "units", "pcs", "pieces", "each",
    }

    def match_tokens(value):
        normalized = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", (value or "").casefold())
        return {word for word in re.findall(r"[a-z0-9]+", normalized) if len(word) > 1 and word not in ignored_words}

    term_words = []
    for term in terms:
        core = term.split("|", 1)[0].strip()
        normalized_core = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", core.casefold())
        ordered_words = [word for word in re.findall(r"[a-z0-9]+", normalized_core) if len(word) > 1 and word not in ignored_words]
        words = set(ordered_words) or match_tokens(term)
        anchor = ordered_words[0] if ordered_words else (next(iter(words)) if words else core.casefold())
        term_words.append((words or {anchor}, anchor))

    pharmacies = list(Pharmacy.objects.filter(
        verification_status=Pharmacy.VerificationStatus.APPROVED,
    ).order_by("name")[:100])
    if not pharmacies:
        return []

    candidate_listings = _public_listings().filter(
        pharmacy_id__in=[pharmacy.pk for pharmacy in pharmacies],
        available_quantity__gt=F("reserved_quantity"),
    ).select_related("product", "pharmacy").order_by("selling_price", "-last_stock_update")[:10000]
    by_pharmacy = {}
    for listing in candidate_listings:
        product = listing.product
        searchable = match_tokens(" ".join((
            product.brand_name, product.generic_name, product.strength, product.pack_size,
            product.manufacturer, product.get_dosage_form_display(),
        )))
        by_pharmacy.setdefault(listing.pharmacy_id, []).append((listing, searchable))

    matches = []
    for pharmacy in pharmacies:
        available = by_pharmacy.get(pharmacy.pk, [])
        picked = []
        used_product_ids = set()
        estimated_total = Decimal("0.00")
        for term, (words, anchor) in zip(terms, term_words):
            # Short entries need a strong token match. Long catalogue titles commonly contain
            # marketing and packaging descriptors, so require the leading product/generic token
            # plus a majority of their meaningful tokens instead of rejecting useful matches.
            threshold = len(words) if len(words) <= 4 else max(2, (len(words) + 1) // 2)
            listing = next((
                item for item, searchable in available
                if item.product_id not in used_product_ids
                and anchor in searchable
                and len(words.intersection(searchable)) >= threshold
            ), None)
            if listing is None:
                break
            used_product_ids.add(listing.product_id)
            picked.append({"requested_name": term, "listing": listing})
            estimated_total += listing.selling_price
        if len(picked) == len(terms):
            matches.append({
                "pharmacy": pharmacy,
                "items": picked,
                "item_count": len(picked),
                "estimated_total": estimated_total,
                "same_pincode": bool(prescription.preferred_pincode and pharmacy.pincode == prescription.preferred_pincode),
            })
    matches.sort(key=lambda result: (
        not result["same_pincode"],
        result["estimated_total"],
        result["pharmacy"].name.casefold(),
    ))
    return matches[:12]


@login_required
def prescription_list(request):
    prescriptions = list(Prescription.objects.filter(owner=request.user).prefetch_related("orders")[:30])
    for prescription in prescriptions:
        prescription.has_linked_orders = prescription.orders.exists()
        prescription.requested_medicine_lines = [line.strip() for line in prescription.requested_medicines.splitlines() if line.strip()]
        prescription.matching_pharmacies = _prescription_pharmacy_matches(prescription)
    return render(request, "marketplace/prescriptions.html", {"prescriptions": prescriptions})


@login_required
def prescription_upload(request):
    if request.method == "POST":
        form = PrescriptionUploadForm(request.POST, request.FILES)
        if form.is_valid():
            prescription = form.save(commit=False)
            prescription.owner = request.user
            prescription.original_filename = request.FILES["file"].name[:255]
            prescription.save()
            _write_audit(request.user, "prescription_uploaded", prescription, f"Prescription #{prescription.pk}; requested medicine count={len([x for x in prescription.requested_medicines.splitlines() if x.strip()])}")
            messages.success(request, "Prescription uploaded privately. You can request a callback or compare pharmacies listing every medicine name you entered.")
            return redirect("prescriptions")
    else:
        form = PrescriptionUploadForm()
    return render(request, "marketplace/prescription_upload.html", {"form": form})


@login_required
@require_POST
def prescription_delete(request, pk):
    prescription = get_object_or_404(Prescription, pk=pk, owner=request.user)
    if prescription.orders.exists():
        messages.error(request, "This prescription is linked to an order and cannot be removed. Contact support if it was attached in error.")
        return redirect("prescriptions")
    stored_file = prescription.file
    prescription_id = prescription.pk
    _write_audit(request.user, "prescription_deleted", prescription, f"Prescription #{prescription_id} removed by owner")
    prescription.delete()
    if stored_file:
        try:
            stored_file.storage.delete(stored_file.name)
        except (OSError, ValueError):
            # The database record is already removed; a stale private file must not block the user.
            pass
    messages.success(request, "Prescription and its private file were removed.")
    return redirect("prescriptions")


@login_required
@require_POST
def prescription_request_call(request, pk):
    prescription = get_object_or_404(Prescription, pk=pk, owner=request.user)
    phone = request.POST.get("callback_phone", "").strip()
    digits = re.sub(r"\D", "", phone)
    if not 7 <= len(digits) <= 15:
        messages.error(request, "Enter a valid contact number so the team can call you.")
        return redirect("prescriptions")
    prescription.callback_phone = phone[:25]
    prescription.callback_requested = True
    prescription.callback_requested_at = timezone.now()
    prescription.save(update_fields=["callback_phone", "callback_requested", "callback_requested_at"])
    _write_audit(request.user, "prescription_callback_requested", prescription, "Customer requested a call to help place the order")
    messages.success(request, "Your callback request is saved. It is visible to the MedMitra team in Admin; no automatic phone call is placed by this website.")
    return redirect("prescriptions")


@login_required
def prescription_download(request, pk):
    prescription = get_object_or_404(Prescription, pk=pk)
    allowed = prescription.owner_id == request.user.id or request.user.is_staff or request.user.is_superuser
    if not allowed:
        allowed = MarketplaceOrder.objects.filter(prescription=prescription, pharmacy__owner=request.user).exists()
    if not allowed:
        raise PermissionDenied
    try:
        response = FileResponse(prescription.file.open("rb"), as_attachment=True, filename=prescription.original_filename or "prescription")
    except (FileNotFoundError, ValueError):
        raise Http404("Prescription file is unavailable.")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def prescription_review(request, pk):
    prescription = get_object_or_404(Prescription, pk=pk)
    owner_pharmacies = Pharmacy.objects.filter(owner=request.user)
    permitted = request.user.is_staff or request.user.is_superuser or MarketplaceOrder.objects.filter(prescription=prescription, pharmacy__in=owner_pharmacies).exists()
    if not permitted:
        raise PermissionDenied
    status = request.POST.get("status", "")
    if status not in {Prescription.Status.APPROVED, Prescription.Status.REJECTED, Prescription.Status.CLARIFICATION}:
        messages.error(request, "Choose a valid review outcome.")
    else:
        prescription.status = status
        prescription.review_note = request.POST.get("review_note", "")[:500]
        prescription.reviewed_by = request.user
        prescription.reviewed_at = timezone.now()
        prescription.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at"])
        _write_audit(request.user, "prescription_reviewed", prescription, f"Outcome={status}")
        messages.success(request, "Prescription review saved.")
    if request.POST.get("return_to") == "detail":
        # Return only to a known order linked to this prescription and authorized
        # for this actor; never accept an arbitrary destination URL.
        return_reference = request.POST.get("return_reference", "").strip()
        linked_order = MarketplaceOrder.objects.filter(
            prescription=prescription, reference=return_reference
        ).select_related("pharmacy").first()
        if linked_order and (
            request.user.is_staff or request.user.is_superuser
            or linked_order.pharmacy.owner_id == request.user.id
        ):
            return redirect("order_detail", reference=linked_order.reference)
    return redirect("retailer_orders")


@login_required
@require_POST
def cart_add(request, listing_id):
    listing = get_object_or_404(_public_listings(), pk=listing_id)
    form = CartAddForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid quantity between 1 and 50.")
        return redirect(request.META.get("HTTP_REFERER", "medicine_search"))
    qty = form.cleaned_data["quantity"]
    existing = CartItem.objects.filter(customer=request.user, listing=listing).first()
    target_qty = qty + existing.quantity if existing else qty
    if target_qty > 50 or not listing.in_stock or target_qty > listing.sellable_quantity:
        messages.error(request, "The requested quantity is not currently available. Please refresh stock information.")
        return redirect(request.META.get("HTTP_REFERER", "medicine_search"))
    item, created = CartItem.objects.get_or_create(customer=request.user, listing=listing, defaults={"quantity": qty})
    if not created:
        item.quantity = target_qty
        item.save(update_fields=["quantity"])
    messages.success(request, "Added to your cart. Cart items from each pharmacy are checked out separately.")
    return redirect("cart_detail")


@login_required
def cart_detail(request):
    items = list(CartItem.objects.filter(customer=request.user).select_related("listing__product", "listing__pharmacy"))
    grouped = {}
    for item in items:
        pharmacy = item.listing.pharmacy
        group = grouped.setdefault(pharmacy.pk, {"pharmacy": pharmacy, "items": [], "subtotal": Decimal("0.00")})
        group["items"].append(item)
        group["subtotal"] += item.subtotal
    groups = list(grouped.values())
    return render(request, "marketplace/cart.html", {"groups": groups, "item_count": len(items)})


@login_required
@require_POST
def cart_update(request, pk):
    item = get_object_or_404(CartItem.objects.select_related("listing"), pk=pk, customer=request.user)
    try:
        qty = int(request.POST.get("quantity", "0"))
    except ValueError:
        qty = 0
    if qty < 1 or qty > 50 or qty > item.listing.sellable_quantity:
        messages.error(request, "Choose a quantity available from this pharmacy (1–50).")
    else:
        item.quantity = qty
        item.save(update_fields=["quantity"])
        messages.success(request, "Cart updated.")
    return redirect("cart_detail")


@login_required
@require_POST
def cart_remove(request, pk):
    get_object_or_404(CartItem, pk=pk, customer=request.user).delete()
    messages.success(request, "Item removed from cart.")
    return redirect("cart_detail")


@login_required
def checkout(request, pharmacy_id):
    pharmacy = get_object_or_404(Pharmacy, pk=pharmacy_id, verification_status=Pharmacy.VerificationStatus.APPROVED)
    cart_items = list(CartItem.objects.filter(customer=request.user, listing__pharmacy=pharmacy).select_related("listing__product", "listing__pharmacy"))
    if not cart_items:
        messages.info(request, "There are no cart items for this pharmacy.")
        return redirect("cart_detail")
    form = CheckoutForm(request.POST or None, customer=request.user, pharmacy=pharmacy)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                # Lock and refresh the cart rows too, so simultaneous double-submits cannot
                # create two orders from the same cart after the first transaction clears it.
                current_cart_items = list(
                    CartItem.objects.select_for_update()
                    .filter(customer=request.user, listing__pharmacy=pharmacy)
                    .select_related("listing__product", "listing__pharmacy")
                    .order_by("pk")
                )
                if not current_cart_items:
                    raise ValidationError("These cart items have already been checked out or removed.")
                locked_items = []
                for cart_item in current_cart_items:
                    listing = PharmacyListing.objects.select_for_update().select_related("product", "pharmacy").get(pk=cart_item.listing_id)
                    if not listing.active or listing.is_expired or listing.pharmacy.verification_status != Pharmacy.VerificationStatus.APPROVED:
                        raise ValidationError(f"{listing.product.brand_name} is no longer available.")
                    if cart_item.quantity > listing.sellable_quantity:
                        raise ValidationError(f"{listing.product.brand_name} is no longer available in the requested quantity. Please update your cart or contact the pharmacy.")
                    locked_items.append((cart_item, listing))
                needs_prescription = any(listing.product.requires_prescription for _, listing in locked_items)
                prescription = form.cleaned_data.get("prescription")
                if needs_prescription and not prescription:
                    raise ValidationError("This order includes prescription-required medicine. Upload a prescription first.")
                if needs_prescription and prescription.owner_id != request.user.id:
                    raise ValidationError("Select one of your own prescriptions.")
                mode = form.cleaned_data["fulfilment"]
                delivery_fee = pharmacy.delivery_fee if mode == MarketplaceOrder.Fulfilment.DELIVERY else Decimal("0.00")
                subtotal = sum((listing.selling_price * cart_item.quantity for cart_item, listing in locked_items), Decimal("0.00"))
                order = MarketplaceOrder.objects.create(
                    customer=request.user, pharmacy=pharmacy, prescription=prescription,
                    fulfilment=mode, delivery_address=form.cleaned_data.get("delivery_address", "").strip(),
                    customer_note=form.cleaned_data.get("customer_note", "").strip(),
                    payment_method=form.cleaned_data["payment_method"],
                    payment_status=MarketplaceOrder.PaymentStatus.PENDING,
                    subtotal=subtotal, delivery_fee=delivery_fee, total=subtotal + delivery_fee,
                )
                OrderStatusEvent.objects.create(order=order, actor=request.user, old_status="", new_status=order.status, note="Order submitted; stock reserved pending pharmacy review")
                _write_audit(request.user, "order_submitted", order, f"Pharmacy #{pharmacy.pk}; fulfilment={mode}; total={order.total}")
                for cart_item, listing in locked_items:
                    MarketplaceOrderItem.objects.create(
                        order=order, listing=listing, product_name_snapshot=str(listing.product),
                        quantity=cart_item.quantity, unit_price=listing.selling_price, mrp_snapshot=listing.mrp,
                    )
                    listing.reserved_quantity += cart_item.quantity
                    listing.save(update_fields=["reserved_quantity", "last_stock_update", "updated_at"])
                    cart_item.delete()
            messages.success(request, f"Request submitted. Reference: {order.reference}. Your order is pending pharmacy confirmation; it is not yet a completed sale.")
            return redirect("order_detail", reference=order.reference)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            cart_items = list(CartItem.objects.filter(customer=request.user, listing__pharmacy=pharmacy).select_related("listing__product", "listing__pharmacy"))
            if not cart_items:
                return redirect("cart_detail")
    subtotal = sum((i.subtotal for i in cart_items), Decimal("0.00"))
    return render(request, "marketplace/checkout.html", {
        "form": form,
        "pharmacy": pharmacy,
        "cart_items": cart_items,
        "subtotal": subtotal,
        "payment_qr_settings": _payment_qr_settings_for_pharmacy(pharmacy),
        "razorpay_enabled": form.razorpay_enabled,
    })


class PaymentGatewayUnavailable(Exception):
    """A controlled gateway error safe to report without exposing provider details."""


def _razorpay_api_request(method, endpoint, payload=None):
    key_id = getattr(settings, "RAZORPAY_KEY_ID", "").strip()
    secret = getattr(settings, "RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not secret:
        raise PaymentGatewayUnavailable("Razorpay is not configured. Ask the administrator to configure test/live keys.")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    token = base64.b64encode(f"{key_id}:{secret}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        f"https://api.razorpay.com/v1/{endpoint.lstrip('/')}",
        data=body,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json", "Accept": "application/json"},
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("Razorpay request failed (%s)", endpoint.split("/")[0])
        raise PaymentGatewayUnavailable("The payment provider could not complete the request. Please try again.") from exc
    if not isinstance(parsed, dict):
        raise PaymentGatewayUnavailable("The payment provider returned an unexpected response.")
    return parsed


@login_required
@require_POST
def razorpay_create_order(request, reference):
    """Create/reuse a Razorpay order only while the request is awaiting the shop."""
    order = get_object_or_404(MarketplaceOrder, reference=reference, customer=request.user)
    if order.payment_method != MarketplaceOrder.PaymentMethod.RAZORPAY:
        raise PermissionDenied
    if order.payment_status == MarketplaceOrder.PaymentStatus.PAID:
        return JsonResponse({"paid": True, "message": "This order is already paid."})
    # Online payment is only initiated for a pending request. The pharmacy cannot
    # accept an online-pay order until payment is verified by the server.
    if order.status != MarketplaceOrder.Status.PENDING:
        return JsonResponse({"error": "This order is no longer awaiting payment."}, status=400)
    if order.total <= Decimal("0.00"):
        return JsonResponse({"error": "The order total is not a valid payment amount."}, status=400)
    try:
        if not order.gateway_order_id:
            amount_paise = int((order.total * Decimal("100")).quantize(Decimal("1")))
            gateway_order = _razorpay_api_request("POST", "orders", {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": order.reference,
                "notes": {"medmitra_reference": order.reference},
            })
            gateway_order_id = gateway_order.get("id", "")
            if not gateway_order_id.startswith("order_"):
                raise PaymentGatewayUnavailable("The payment provider did not return a valid order reference.")
            # Recheck after the network call: the customer may have cancelled in
            # another tab while the gateway order was being created.
            with transaction.atomic():
                locked_order = MarketplaceOrder.objects.select_for_update().get(pk=order.pk)
                if locked_order.status != MarketplaceOrder.Status.PENDING or locked_order.payment_status == MarketplaceOrder.PaymentStatus.PAID:
                    return JsonResponse({"error": "This order changed while payment was starting. Refresh the order page before continuing."}, status=409)
                if not locked_order.gateway_order_id:
                    locked_order.gateway_order_id = gateway_order_id
                    locked_order.save(update_fields=["gateway_order_id", "updated_at"])
                order = locked_order
        return JsonResponse({
            "key_id": getattr(settings, "RAZORPAY_KEY_ID", "").strip(),
            "order_id": order.gateway_order_id,
            "amount": int((order.total * Decimal("100")).quantize(Decimal("1"))),
            "currency": "INR",
            "name": "MedMitra",
            "description": f"Medicine order {order.reference}",
            "reference": order.reference,
            "prefill": {"name": request.user.get_full_name() or request.user.get_username(), "email": getattr(request.user, "email", "")},
        })
    except PaymentGatewayUnavailable as exc:
        return JsonResponse({"error": str(exc)}, status=503)


@login_required
@require_POST
def razorpay_verify_payment(request, reference):
    """Verify signature, amount, currency and captured status using the provider API."""
    order = get_object_or_404(MarketplaceOrder, reference=reference, customer=request.user)
    if order.payment_method != MarketplaceOrder.PaymentMethod.RAZORPAY:
        raise PermissionDenied
    if order.payment_status == MarketplaceOrder.PaymentStatus.PAID:
        return JsonResponse({"ok": True, "message": "Payment is already confirmed."})
    order_id = request.POST.get("razorpay_order_id", "").strip()
    payment_id = request.POST.get("razorpay_payment_id", "").strip()
    signature = request.POST.get("razorpay_signature", "").strip()
    secret = getattr(settings, "RAZORPAY_KEY_SECRET", "").strip()
    if not secret or not order.gateway_order_id or order_id != order.gateway_order_id:
        return JsonResponse({"error": "The payment order could not be verified. Please contact support."}, status=400)
    expected_signature = hmac.new(
        secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not payment_id.startswith("pay_") or not signature or not hmac.compare_digest(expected_signature, signature):
        _write_audit(request.user, "razorpay_signature_rejected", order, "Payment callback signature validation failed")
        return JsonResponse({"error": "Payment verification failed. Do not retry by refreshing this page; contact support if your bank was debited."}, status=400)
    try:
        gateway_payment = _razorpay_api_request("GET", f"payments/{payment_id}")
        amount_paise = int((order.total * Decimal("100")).quantize(Decimal("1")))
        if (
            gateway_payment.get("order_id") != order.gateway_order_id
            or gateway_payment.get("amount") != amount_paise
            or gateway_payment.get("currency") != "INR"
        ):
            return JsonResponse({"error": "The payment details do not match this order. Please contact support."}, status=400)
        if gateway_payment.get("status") == "authorized":
            _razorpay_api_request("POST", f"payments/{payment_id}/capture", {"amount": amount_paise, "currency": "INR"})
            gateway_payment = _razorpay_api_request("GET", f"payments/{payment_id}")
        if gateway_payment.get("status") != "captured":
            return JsonResponse({"error": "The payment is not captured yet. Please check the payment status before trying again."}, status=409)
    except PaymentGatewayUnavailable as exc:
        return JsonResponse({"error": str(exc)}, status=503)

    # A verified capture must be recorded even if the customer cancelled while
    # the gateway window was open. In that race, route the order to manual refund
    # review rather than losing evidence that money was captured.
    with transaction.atomic():
        locked_order = MarketplaceOrder.objects.select_for_update().get(pk=order.pk)
        if locked_order.payment_status == MarketplaceOrder.PaymentStatus.PAID:
            return JsonResponse({"ok": True, "message": "Payment is already confirmed."})
        old_status = locked_order.status
        refund_review_needed = old_status in {
            MarketplaceOrder.Status.CANCELLED,
            MarketplaceOrder.Status.REJECTED,
            MarketplaceOrder.Status.REFUND_PENDING,
            MarketplaceOrder.Status.REFUNDED,
        }
        locked_order.gateway_payment_id = payment_id
        locked_order.payment_status = MarketplaceOrder.PaymentStatus.PAID
        locked_order.payment_verified_at = timezone.now()
        locked_order.payment_review_note = "Payment verified with Razorpay's server API."
        if refund_review_needed:
            locked_order.status = MarketplaceOrder.Status.REFUND_PENDING
            locked_order.payment_review_note = "Razorpay confirmed captured payment after order cancellation/rejection; refund requires manual review."
        locked_order.save(update_fields=["gateway_payment_id", "payment_status", "payment_verified_at", "payment_review_note", "status", "updated_at"])
        if refund_review_needed and old_status != MarketplaceOrder.Status.REFUND_PENDING:
            OrderStatusEvent.objects.create(
                order=locked_order, actor=request.user, old_status=old_status,
                new_status=MarketplaceOrder.Status.REFUND_PENDING,
                note="Payment was captured after the order became terminal; manual refund review required.",
            )
        _write_audit(request.user, "razorpay_payment_verified", locked_order, f"Gateway payment verified: {payment_id}; refund_review_needed={refund_review_needed}")
    if refund_review_needed:
        return JsonResponse({"ok": True, "message": "Payment was verified, but the order had been cancelled. Contact MedMitra support for manual refund handling."})
    return JsonResponse({"ok": True, "message": "Payment confirmed. Your order is now awaiting pharmacy confirmation."})


@login_required
@require_POST
def payment_proof_upload(request, reference):
    order = get_object_or_404(MarketplaceOrder, reference=reference, customer=request.user)
    pickup_qr_eligible = (
        order.fulfilment == MarketplaceOrder.Fulfilment.PICKUP
        and order.payment_method == MarketplaceOrder.PaymentMethod.PAY_AT_STORE
        and bool(_payment_qr_settings_for_pharmacy(order.pharmacy))
    )
    if order.payment_method != MarketplaceOrder.PaymentMethod.SBI_QR and not pickup_qr_eligible:
        raise PermissionDenied
    form = PaymentProofForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = form.errors.get("payment_proof") or form.errors.get("payment_reference") or []
        messages.error(request, " ".join(errors) or "Check the payment proof form and try again.")
        return redirect("order_detail", reference=order.reference)

    old_name = ""
    try:
        with transaction.atomic():
            order = MarketplaceOrder.objects.select_for_update().get(pk=order.pk, customer=request.user)
            if order.status != MarketplaceOrder.Status.PENDING:
                messages.error(request, "Payment proof can only be submitted while the order is awaiting pharmacy confirmation.")
                return redirect("order_detail", reference=order.reference)
            if order.payment_status not in {MarketplaceOrder.PaymentStatus.PENDING, MarketplaceOrder.PaymentStatus.PROOF_REJECTED}:
                messages.info(request, "Payment proof has already been submitted or this order is paid.")
                return redirect("order_detail", reference=order.reference)
            if order.fulfilment == MarketplaceOrder.Fulfilment.PICKUP and order.payment_method == MarketplaceOrder.PaymentMethod.PAY_AT_STORE:
                if not _payment_qr_settings_for_pharmacy(order.pharmacy):
                    messages.error(request, "This pharmacy has not configured QR / bank payment details yet.")
                    return redirect("order_detail", reference=order.reference)
                order.payment_method = MarketplaceOrder.PaymentMethod.SBI_QR
            old_name = order.payment_proof.name if order.payment_proof else ""
            order.payment_proof = form.cleaned_data["payment_proof"]
            order.payment_reference = form.cleaned_data["payment_reference"].strip()
            order.payment_status = MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED
            order.payment_review_note = "Payment proof submitted and awaiting pharmacy/admin verification."
            order.payment_verified_at = None
            order.payment_verified_by = None
            order.save(update_fields=["payment_method", "payment_proof", "payment_reference", "payment_status", "payment_review_note", "payment_verified_at", "payment_verified_by", "updated_at"])
            _write_audit(request.user, "upi_payment_proof_submitted", order, "Customer submitted QR transfer proof for review")
    except MarketplaceOrder.DoesNotExist:
        raise Http404("Order not found.")

    if old_name and old_name != order.payment_proof.name:
        order.payment_proof.storage.delete(old_name)
    messages.success(request, "Payment proof uploaded. The pharmacy must verify the transfer before accepting the order.")
    return redirect("order_detail", reference=order.reference)


@login_required
@require_POST
def payment_proof_review(request, reference):
    decision = request.POST.get("decision", "").strip()
    note = request.POST.get("note", "").strip()[:300]
    if decision not in {"approve", "reject"}:
        messages.error(request, "Choose approve or reject for the payment proof.")
        return redirect("order_detail", reference=reference)
    try:
        with transaction.atomic():
            order = get_object_or_404(
                MarketplaceOrder.objects.select_for_update().select_related("pharmacy", "customer"),
                reference=reference,
            )
            if not (request.user.is_superuser or order.pharmacy.owner_id == request.user.id):
                raise PermissionDenied
            if (
                order.status != MarketplaceOrder.Status.PENDING
                or order.payment_method != MarketplaceOrder.PaymentMethod.SBI_QR
                or order.payment_status != MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED
                or not order.payment_proof
            ):
                messages.error(request, "There is no payment proof awaiting review for this order.")
                return redirect("order_detail", reference=order.reference)
            if decision == "approve":
                order.payment_status = MarketplaceOrder.PaymentStatus.PAID
                order.payment_verified_by = request.user
                order.payment_verified_at = timezone.now()
                order.payment_review_note = note or "QR payment proof verified by pharmacy/admin."
                action = "upi_payment_proof_approved"
                message = "Payment proof verified. The pharmacy can now accept the order."
            else:
                order.payment_status = MarketplaceOrder.PaymentStatus.PROOF_REJECTED
                order.payment_verified_by = None
                order.payment_verified_at = None
                order.payment_review_note = note or "Payment proof was not verified. Please upload a clearer proof or contact the pharmacy."
                action = "upi_payment_proof_rejected"
                message = "Payment proof rejected. The customer can submit it again."
            order.save(update_fields=["payment_status", "payment_verified_by", "payment_verified_at", "payment_review_note", "updated_at"])
            _write_audit(request.user, action, order, f"Payment proof review: {decision}")
    except MarketplaceOrder.DoesNotExist:
        raise Http404("Order not found.")
    messages.success(request, message)
    return redirect("order_detail", reference=order.reference)


@login_required
def payment_proof_download(request, reference):
    order = get_object_or_404(MarketplaceOrder.objects.select_related("pharmacy", "customer"), reference=reference)
    if not (request.user.is_superuser or request.user.id == order.customer_id or request.user.id == order.pharmacy.owner_id):
        raise PermissionDenied
    if not order.payment_proof:
        raise Http404("Payment proof has not been uploaded.")
    try:
        file_handle = order.payment_proof.open("rb")
    except (OSError, ValueError):
        raise Http404("Payment proof is unavailable.")
    suffix = order.payment_proof.name.rsplit(".", 1)[-1]
    return FileResponse(file_handle, as_attachment=True, filename=f"payment-proof-{order.reference}.{suffix}")


@login_required
@require_POST
def retailer_mark_payment_collected(request, pk):
    order = get_object_or_404(MarketplaceOrder.objects.select_related("pharmacy", "customer"), pk=pk)
    if not _is_pharmacy_owner(request.user, order.pharmacy):
        raise PermissionDenied
    if order.payment_status == MarketplaceOrder.PaymentStatus.COLLECTED:
        messages.info(request, "Cash was already marked as collected for this order.")
        return redirect("order_detail", reference=order.reference)
    if order.payment_method not in {MarketplaceOrder.PaymentMethod.COD, MarketplaceOrder.PaymentMethod.PAY_AT_STORE}:
        messages.error(request, "This order uses online payment and cannot be marked as a cash collection.")
        return redirect("order_detail", reference=order.reference)
    if order.status not in {
        MarketplaceOrder.Status.READY,
        MarketplaceOrder.Status.OUT_FOR_DELIVERY,
        MarketplaceOrder.Status.COMPLETED,
    }:
        messages.error(request, "Mark cash collected only when the order is ready for pickup, out for delivery, or completed.")
        return redirect("order_detail", reference=order.reference)
    order.payment_status = MarketplaceOrder.PaymentStatus.COLLECTED
    order.payment_collected_at = timezone.now()
    order.payment_collected_by = request.user
    order.save(update_fields=["payment_status", "payment_collected_at", "payment_collected_by", "updated_at"])
    _write_audit(request.user, "cash_payment_collected", order, f"Payment collected for order {order.reference}")
    messages.success(request, "Cash collection recorded. The printable receipt now shows payment received.")
    return redirect("order_detail", reference=order.reference)


@login_required
def order_detail(request, reference):
    order = get_object_or_404(MarketplaceOrder.objects.select_related("customer", "pharmacy", "prescription").prefetch_related("items", "status_events"), reference=reference)
    owner_access = _is_pharmacy_owner(request.user, order.pharmacy)
    if order.customer_id != request.user.id and not owner_access:
        raise PermissionDenied
    can_collect_payment = (
        owner_access
        and order.payment_method in {MarketplaceOrder.PaymentMethod.COD, MarketplaceOrder.PaymentMethod.PAY_AT_STORE}
        and order.payment_status == MarketplaceOrder.PaymentStatus.PENDING
        and order.status in {
            MarketplaceOrder.Status.READY,
            MarketplaceOrder.Status.OUT_FOR_DELIVERY,
            MarketplaceOrder.Status.COMPLETED,
        }
    )
    progress = [
        (MarketplaceOrder.Status.PENDING, "Request sent"),
        (MarketplaceOrder.Status.ACCEPTED, "Accepted"),
        (MarketplaceOrder.Status.PROCESSING, "Preparing"),
        (MarketplaceOrder.Status.READY, "Ready"),
    ]
    if order.fulfilment == MarketplaceOrder.Fulfilment.DELIVERY:
        progress.append((MarketplaceOrder.Status.OUT_FOR_DELIVERY, "On the way"))
    progress.append((MarketplaceOrder.Status.COMPLETED, "Completed"))
    current_step = next((index for index, (value, _) in enumerate(progress) if value == order.status), -1)
    order_progress_steps = []
    for index, (value, label) in enumerate(progress):
        state = "upcoming"
        if current_step >= 0 and index < current_step:
            state = "done"
        elif index == current_step:
            state = "current"
        order_progress_steps.append({"value": value, "label": label, "state": state})
    order_terminal_status = order.get_status_display() if order.status in {
        MarketplaceOrder.Status.REJECTED,
        MarketplaceOrder.Status.CANCELLED,
        MarketplaceOrder.Status.REFUND_PENDING,
        MarketplaceOrder.Status.REFUNDED,
    } else ""
    show_pickup_qr = (
        order.fulfilment == MarketplaceOrder.Fulfilment.PICKUP
        and order.payment_method == MarketplaceOrder.PaymentMethod.PAY_AT_STORE
        and order.payment_status in {MarketplaceOrder.PaymentStatus.PENDING, MarketplaceOrder.PaymentStatus.PROOF_REJECTED}
        and order.status == MarketplaceOrder.Status.PENDING
    )
    qr_payment_settings = _payment_qr_settings_for_pharmacy(order.pharmacy) if (order.payment_method == MarketplaceOrder.PaymentMethod.SBI_QR or show_pickup_qr) else None
    can_upload_payment_proof = (
        order.customer_id == request.user.id
        and (order.payment_method == MarketplaceOrder.PaymentMethod.SBI_QR or show_pickup_qr)
        and bool(qr_payment_settings)
        and order.status == MarketplaceOrder.Status.PENDING
        and order.payment_status in {MarketplaceOrder.PaymentStatus.PENDING, MarketplaceOrder.PaymentStatus.PROOF_REJECTED}
    )
    payment_proof_form = PaymentProofForm() if can_upload_payment_proof else None
    can_view_payment_proof = bool(order.payment_proof) and (
        request.user.is_superuser or order.customer_id == request.user.id or order.pharmacy.owner_id == request.user.id
    )
    can_review_payment_proof = (
        request.user.is_superuser or order.pharmacy.owner_id == request.user.id
    ) and order.payment_method == MarketplaceOrder.PaymentMethod.SBI_QR and order.status == MarketplaceOrder.Status.PENDING and order.payment_status == MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED and bool(order.payment_proof)

    # Build a management panel for the retailer on this page, so the dashboard's
    # Open/Manage action can accept, reject, advance, and review the same order.
    has_prescription_items = order.items.filter(listing__product__requires_prescription=True).exists()
    prescription_approved = bool(order.prescription and order.prescription.status == Prescription.Status.APPROVED)
    has_expired_items = order.items.filter(listing__expiry_date__lt=timezone.localdate()).exists()
    can_retailer_accept_order = bool(owner_access and order.status == MarketplaceOrder.Status.PENDING)
    retailer_accept_block_reason = ""
    if can_retailer_accept_order:
        if order.payment_status == MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED:
            can_retailer_accept_order = False
            retailer_accept_block_reason = "Review the submitted payment proof before accepting this order."
        elif order.payment_method in {MarketplaceOrder.PaymentMethod.RAZORPAY, MarketplaceOrder.PaymentMethod.SBI_QR} and order.payment_status != MarketplaceOrder.PaymentStatus.PAID:
            can_retailer_accept_order = False
            retailer_accept_block_reason = "Online payment must be verified before this order can be accepted."
        elif (
            order.fulfilment == MarketplaceOrder.Fulfilment.PICKUP
            and order.payment_method == MarketplaceOrder.PaymentMethod.PAY_AT_STORE
            and bool(_payment_qr_settings_for_pharmacy(order.pharmacy))
            and order.payment_status != MarketplaceOrder.PaymentStatus.PAID
        ):
            can_retailer_accept_order = False
            retailer_accept_block_reason = "This pharmacy requires QR / bank-transfer proof to be verified before accepting pickup orders."
        elif has_prescription_items and not prescription_approved:
            can_retailer_accept_order = False
            retailer_accept_block_reason = "Approve the required prescription before accepting this order."
        elif has_expired_items:
            can_retailer_accept_order = False
            retailer_accept_block_reason = "This order contains an expired batch and cannot be accepted."

    can_retailer_reject_order = bool(
        owner_access and order.status == MarketplaceOrder.Status.PENDING
        and order.payment_status != MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED
    )
    razorpay_enabled = bool(
        getattr(settings, "RAZORPAY_KEY_ID", "").strip()
        and getattr(settings, "RAZORPAY_KEY_SECRET", "").strip()
    )
    return render(request, "marketplace/order_detail.html", {
        "order": order,
        "owner_access": owner_access,
        "can_collect_payment": can_collect_payment,
        "order_progress_steps": order_progress_steps,
        "order_terminal_status": order_terminal_status,
        "payment_qr_settings": qr_payment_settings,
        "show_qr_payment": order.payment_method == MarketplaceOrder.PaymentMethod.SBI_QR or show_pickup_qr,
        "can_upload_payment_proof": can_upload_payment_proof,
        "payment_proof_form": payment_proof_form,
        "can_view_payment_proof": can_view_payment_proof,
        "can_review_payment_proof": can_review_payment_proof,
        "can_retailer_accept_order": can_retailer_accept_order,
        "retailer_accept_block_reason": retailer_accept_block_reason,
        "can_retailer_reject_order": can_retailer_reject_order,
        "has_prescription_items": has_prescription_items,
        "prescription_approved": prescription_approved,
        "razorpay_enabled": razorpay_enabled,
        "razorpay_key_id": getattr(settings, "RAZORPAY_KEY_ID", "").strip(),
    })


@login_required
def order_receipt_pdf(request, reference):
    """Download a compact, private order/payment receipt PDF for the order parties."""
    from io import BytesIO
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

    order = get_object_or_404(
        MarketplaceOrder.objects.select_related("customer", "pharmacy").prefetch_related("items"),
        reference=reference,
    )
    owner_access = _is_pharmacy_owner(request.user, order.pharmacy)
    if order.customer_id != request.user.id and not owner_access and not request.user.is_superuser:
        raise PermissionDenied

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm,
        topMargin=13 * mm, bottomMargin=15 * mm,
        title=f"MedMitra receipt {order.reference}", author="MedMitra",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="MMReceiptTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=20, leading=23, alignment=0, textColor=colors.HexColor("#167f73"),
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptSubtitle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10, leading=13, textColor=colors.HexColor("#263f3b"), spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptBody", parent=styles["Normal"], fontName="Helvetica",
        fontSize=8.5, leading=11, textColor=colors.HexColor("#263f3b"),
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptSmall", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.5, leading=9, textColor=colors.HexColor("#526963"),
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptCellRight", parent=styles["MMReceiptBody"], alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptCellBold", parent=styles["MMReceiptBody"], fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptHeaderCell", parent=styles["MMReceiptBody"], fontName="Helvetica-Bold",
        textColor=colors.white,
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptItem", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.2, leading=8.2, textColor=colors.HexColor("#263f3b"),
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptItemRight", parent=styles["MMReceiptItem"], alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="MMReceiptItemHeader", parent=styles["MMReceiptItem"], fontName="Helvetica-Bold",
        textColor=colors.white,
    ))

    def text(value, style="MMReceiptBody"):
        # ReportLab Paragraph interprets XML-like markup. Escape all model/user data.
        raw = str(value or "—").encode("cp1252", "replace").decode("cp1252")
        value = escape(raw)
        return Paragraph(value.replace("\n", "<br/>"), styles[style])

    def money(value):
        # Use INR text in the PDF because the built-in Helvetica font lacks the rupee glyph.
        return f"INR {Decimal(value or 0):,.2f}"

    paid = order.payment_status in {
        MarketplaceOrder.PaymentStatus.PAID,
        MarketplaceOrder.PaymentStatus.COLLECTED,
    }
    title = "PAYMENT RECEIPT" if paid else "ORDER RECEIPT — PAYMENT NOT YET CONFIRMED"
    story = [
        Paragraph("MedMitra", styles["MMReceiptTitle"]),
        Paragraph(escape(title), styles["MMReceiptSubtitle"]),
    ]
    created = timezone.localtime(order.created_at).strftime("%d %b %Y, %I:%M %p") if order.created_at else "—"
    customer_name = order.customer.get_full_name().strip() or order.customer.get_username()
    store_address = getattr(order.pharmacy, "full_address", "") or getattr(order.pharmacy, "address", "")
    fulfilment_destination = order.delivery_address if order.fulfilment == MarketplaceOrder.Fulfilment.DELIVERY else "Collect at pharmacy counter"
    metadata = [
        [text("Order reference", "MMReceiptSmall"), text(order.reference, "MMReceiptCellBold"), text("Order date", "MMReceiptSmall"), text(created)],
        [text("Customer", "MMReceiptSmall"), text(customer_name), text("Order status", "MMReceiptSmall"), text(order.get_status_display())],
        [text("Pharmacy", "MMReceiptSmall"), text(order.pharmacy.name), text("Fulfilment", "MMReceiptSmall"), text(order.get_fulfilment_display())],
        [text("Store address", "MMReceiptSmall"), text(store_address), text("Destination", "MMReceiptSmall"), text(fulfilment_destination)],
    ]
    meta_table = Table(metadata, colWidths=[25 * mm, 64 * mm, 25 * mm, 54 * mm], hAlign="LEFT")
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f8f6")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e7e2")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9e7e2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([meta_table, Spacer(1, 4 * mm), Paragraph("Items", styles["MMReceiptSubtitle"])])

    item_rows = [[text("Medicine / product", "MMReceiptItemHeader"), text("Qty", "MMReceiptItemHeader"), text("Unit price", "MMReceiptItemHeader"), text("Line total", "MMReceiptItemHeader")]]
    for item in order.items.all():
        item_rows.append([
            text(item.product_name_snapshot, "MMReceiptItem"),
            text(item.quantity, "MMReceiptItemRight"),
            text(money(item.unit_price), "MMReceiptItemRight"),
            text(money(item.subtotal), "MMReceiptItemRight"),
        ])
    if len(item_rows) == 1:
        item_rows.append([text("No item details recorded"), text("—"), text("—"), text("—")])
    item_table = Table(item_rows, colWidths=[110 * mm, 13 * mm, 29 * mm, 30 * mm], repeatRows=1, hAlign="LEFT")
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#167f73")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#167f73")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#dbe6e2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.extend([item_table, Spacer(1, 3 * mm)])

    totals = [
        [text("Items subtotal"), text(money(order.subtotal), "MMReceiptCellRight")],
        [text("Delivery fee"), text(money(order.delivery_fee), "MMReceiptCellRight")],
        [text("Total" , "MMReceiptCellBold"), text(money(order.total), "MMReceiptCellRight")],
    ]
    totals_table = Table(totals, colWidths=[126 * mm, 42 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.HexColor("#167f73")),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#edf7f3")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([totals_table, Spacer(1, 5 * mm)])

    payment_rows = [
        [text("Payment method", "MMReceiptSmall"), text(order.get_payment_method_display()),
         text("Payment status", "MMReceiptSmall"), text(order.get_payment_status_display())],
    ]
    if order.payment_verified_at:
        payment_rows.append([text("Verified at", "MMReceiptSmall"), text(timezone.localtime(order.payment_verified_at).strftime("%d %b %Y, %I:%M %p")), text("Verified by", "MMReceiptSmall"), text(order.payment_verified_by.get_username() if order.payment_verified_by else "Payment gateway")])
    if order.payment_collected_at:
        payment_rows.append([text("Collected at", "MMReceiptSmall"), text(timezone.localtime(order.payment_collected_at).strftime("%d %b %Y, %I:%M %p")), text("Collected by", "MMReceiptSmall"), text(order.payment_collected_by.get_username() if order.payment_collected_by else "Pharmacy")])
    pay_table = Table(payment_rows, colWidths=[25 * mm, 64 * mm, 25 * mm, 54 * mm], hAlign="LEFT")
    pay_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e7e2")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9e7e2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(KeepTogether([
        Paragraph("Payment details", styles["MMReceiptSubtitle"]), pay_table, Spacer(1, 4 * mm),
        text("Verified payments and recorded cash collections are receipts. If payment status is pending or proof is awaiting review, this document is an order receipt only and is not proof of payment.", "MMReceiptSmall"),
    ]))

    def draw_page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d9e7e2"))
        canvas.setLineWidth(0.5)
        canvas.line(14 * mm, 10 * mm, A4[0] - 14 * mm, 10 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#71827c"))
        canvas.drawString(14 * mm, 6 * mm, f"MedMitra · {order.reference}")
        canvas.drawRightString(A4[0] - 14 * mm, 6 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="MedMitra-{order.reference}-receipt.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response


@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def marketplace_admin_dashboard(request):
    context = {
        "customer_count": get_user_model().objects.filter(is_staff=False, is_superuser=False).count(),
        "pharmacy_count": Pharmacy.objects.count(),
        "pending_pharmacies": Pharmacy.objects.filter(verification_status=Pharmacy.VerificationStatus.PENDING).order_by("created_at"),
        "managed_pharmacies": Pharmacy.objects.exclude(verification_status=Pharmacy.VerificationStatus.PENDING).order_by("-updated_at")[:20],
        "verified_pharmacies": Pharmacy.objects.filter(verification_status=Pharmacy.VerificationStatus.APPROVED).count(),
        "medicine_count": MedicineProduct.objects.filter(active=True).count(),
        "listing_count": PharmacyListing.objects.filter(active=True).count(),
        "pending_orders": MarketplaceOrder.objects.filter(status=MarketplaceOrder.Status.PENDING).count(),
        "recent_orders": MarketplaceOrder.objects.select_related("customer", "pharmacy")[:10],
        "recent_audit_events": MarketplaceAuditLog.objects.select_related("actor")[:8],
    }
    return render(request, "marketplace/admin_dashboard.html", context)


@user_passes_test(lambda u: u.is_staff or u.is_superuser)
@require_POST
def admin_pharmacy_status(request, pk):
    pharmacy = get_object_or_404(Pharmacy, pk=pk)
    status = request.POST.get("status", "")
    if status not in {Pharmacy.VerificationStatus.APPROVED, Pharmacy.VerificationStatus.REJECTED, Pharmacy.VerificationStatus.SUSPENDED}:
        messages.error(request, "Choose a valid pharmacy status.")
    else:
        pharmacy.verification_status = status
        pharmacy.verification_note = request.POST.get("note", "")[:240]
        pharmacy.verified_at = timezone.now() if status == Pharmacy.VerificationStatus.APPROVED else None
        pharmacy.save(update_fields=["verification_status", "verification_note", "verified_at", "updated_at"])
        _write_audit(request.user, "pharmacy_status_changed", pharmacy, f"Status={status}; note={pharmacy.verification_note[:100]}")
        messages.success(request, f"{pharmacy.name} status changed to {pharmacy.get_verification_status_display()}.")
    return redirect("marketplace_admin_dashboard")


def content_page(request, slug):
    pages = {
        "about": ("About MedMitra", "A local pharmacy discovery and inventory coordination project.", "MedMitra helps customers discover listed medicines, compare participating pharmacy prices and send order requests. Pharmacy listings appear publicly only after administrator review. Availability is based on retailer-updated data and can change; customers should confirm stock before visiting.\n\nMedMitra is a software marketplace concept, not a medical provider. It does not diagnose, prescribe or replace advice from a qualified healthcare professional."),
        "contact": ("Contact and support", "Questions about an order or a pharmacy listing?", "For an existing order, sign in and open your order details to see its reference and the selected pharmacy. Contact the pharmacy using the contact information shown on its verified profile.\n\nFor account, privacy or platform issues, contact the project administrator using the support channel configured by your deployment owner. This demo does not send SMS or WhatsApp messages unless an external provider is deliberately configured."),
        "privacy": ("Privacy overview", "Sensitive documents and account data should be handled carefully.", "MedMitra stores account data, order request details and private prescription uploads needed for the workflows shown. Prescription downloads are permission-checked in the application and the files are not linked directly from public page templates.\n\nDo not upload real health documents to an unreviewed demo deployment. Before production use, the operator must configure durable private storage, retention and deletion policies, backup protection, access monitoring, applicable privacy notices and required legal reviews."),
        "terms": ("Terms of use", "Please understand what a MedMitra listing represents.", "MedMitra is a pharmacy discovery and order-request interface. A submitted request is not a completed sale and is not a guarantee that a medicine is available. Stock, listed prices, delivery fees and business hours are supplied by participating pharmacies and may change.\n\nThe platform does not recommend medicine substitutes, dosage or self-treatment. Prescription-required products must be reviewed by an appropriately authorized professional before an order can be accepted. Do not use this college-project application for real transactions until applicable pharmacy, drug-sale, privacy, consumer protection, payments and delivery requirements have been reviewed and met."),
    }
    page = pages.get(slug)
    if not page:
        from django.http import Http404
        raise Http404
    return render(request, "marketplace/content_page.html", {"page_title": page[0], "page_intro": page[1], "page_content": page[2]})
