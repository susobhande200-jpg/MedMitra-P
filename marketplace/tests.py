from decimal import Decimal
import hashlib
import hmac

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.conf import settings
from django.urls import reverse
from django.http import Http404
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

from config.urls import safe_development_media

from .models import (
    MedicineCategory, MedicineProduct, Pharmacy, PharmacyListing, CartItem,
    MarketplaceOrder, MarketplaceOrderItem, MarketplaceAuditLog, FooterSocialLink,
    HomepageSectionSetting, HomepageCategoryTile, HomepageShowcaseProduct, HomepageMembershipBanner, HomepageImageBanner,
    Prescription, MarketplacePaymentSettings, PharmacyCounterSale, PharmacyCounterSaleItem,
)
from .views import _transition_order
from .forms import ListingForm, PharmacyPaymentDetailsForm


class MarketplaceSmokeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(username="customer1", password="Testpass!123")
        self.owner = User.objects.create_user(username="owner1", password="Testpass!123")
        self.other = User.objects.create_user(username="other1", password="Testpass!123")
        category = MedicineCategory.objects.create(name="Demo Essentials", slug="demo-essentials")
        product = MedicineProduct.objects.create(brand_name="DEMO Paracetamol", generic_name="Demo ingredient", strength="500 mg", dosage_form="tablet", category=category)
        self.pharmacy = Pharmacy.objects.create(owner=self.owner, name="DEMO Verified Pharmacy", phone="0000000000", address="1 Demo Street", city="Sampletown", state="West Bengal", pincode="000000", licence_number="DEMO-LIC", verification_status=Pharmacy.VerificationStatus.APPROVED)
        self.listing = PharmacyListing.objects.create(pharmacy=self.pharmacy, product=product, mrp=Decimal("20.00"), selling_price=Decimal("15.00"), available_quantity=10)

    def tearDown(self):
        # Unit tests use uploaded fixtures; clean files from media and private storage.
        for prescription in Prescription.objects.all():
            if prescription.file:
                prescription.file.delete(save=False)
        for order in MarketplaceOrder.objects.all():
            if order.payment_proof:
                order.payment_proof.delete(save=False)
        for config in MarketplacePaymentSettings.objects.all():
            if config.qr_image:
                config.qr_image.delete(save=False)
        for pharmacy in Pharmacy.objects.all():
            if pharmacy.payment_qr_image:
                pharmacy.payment_qr_image.delete(save=False)
        super().tearDown()

    def test_homepage_is_pharmacy_first(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Find your medicine")
        self.assertContains(response, "MedMitra")
        self.assertNotContains(response, "MediSearch")
        self.assertNotContains(response, "MediKhoj")
        self.assertNotContains(response, "Reviewed store listings")
        self.assertNotContains(response, "Price comparison")
        self.assertNotContains(response, "PIN code search")


    def test_active_footer_social_links_render_only_when_enabled(self):
        FooterSocialLink.objects.create(
            platform=FooterSocialLink.Platform.INSTAGRAM,
            url="https://www.instagram.com/",
            label="Instagram",
            sort_order=1,
        )
        FooterSocialLink.objects.create(
            platform=FooterSocialLink.Platform.FACEBOOK,
            url="https://www.facebook.com/",
            is_active=False,
            sort_order=2,
        )
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Follow MedMitra")
        self.assertContains(response, 'href="https://www.instagram.com/"')
        self.assertNotContains(response, "https://www.facebook.com/")

    def test_footer_social_link_management_is_superuser_only(self):
        model_admin = django_admin.site._registry[FooterSocialLink]
        factory = RequestFactory()
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        request = factory.get("/admin/marketplace/footersociallink/")
        request.user = self.owner
        self.assertFalse(model_admin.has_module_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))

        superuser = get_user_model().objects.create_superuser(
            username="siteadmin", email="siteadmin@example.test", password="Testpass!123"
        )
        request.user = superuser
        self.assertTrue(model_admin.has_module_permission(request))
        self.assertTrue(model_admin.has_add_permission(request))

    def test_search_returns_approved_listings_and_add_to_cart_form(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("medicine_search"), {"q": "Paracetamol"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DEMO Paracetamol")
        self.assertContains(response, "Add to cart")
        self.assertContains(response, reverse("cart_add", args=[self.listing.pk]))

    def test_guest_search_offers_sign_in_before_add_to_cart(self):
        response = self.client.get(reverse("medicine_search"), {"q": "Paracetamol"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in to add")

    def test_shop_can_add_new_catalogue_medicine_from_listing_form(self):
        self.pharmacy.verification_status = Pharmacy.VerificationStatus.PENDING
        self.pharmacy.save()
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("retailer_listing_add") + f"?pharmacy={self.pharmacy.pk}",
            {
                "new_catalogue_product": "on",
                "new_product_name": "Shop Added Demo Product",
                "new_generic_name": "Demo ingredient",
                "new_strength": "10 mg",
                "new_dosage_form": "tablet",
                "new_pack_size": "10 tablets",
                "new_manufacturer": "Demo manufacturer",
                "new_requires_prescription": "",
                "mrp": "120.00",
                "selling_price": "100.00",
                "available_quantity": "8",
                "batch_number": "TEST-BATCH",
                "expiry_date": "",
                "active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = MedicineProduct.objects.get(brand_name="Shop Added Demo Product", strength="10 mg")
        listing = PharmacyListing.objects.get(pharmacy=self.pharmacy, product=product)
        self.assertEqual(listing.selling_price, Decimal("100.00"))
        self.assertTrue(listing.active)
        # A pending pharmacy's inventory remains private in public search.
        public_response = self.client.get(reverse("medicine_search"), {"q": "Shop Added Demo Product"})
        self.assertNotContains(public_response, self.pharmacy.name)

    def test_shop_listing_form_explains_new_catalogue_item_flow(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("retailer_listing_add") + f"?pharmacy={self.pharmacy.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add a medicine that is not in the catalogue")
        self.assertContains(response, "new_product_name")


    def test_public_pages_do_not_disclose_exact_stock_counts(self):
        urls = [
            reverse("home"),
            reverse("medicine_search"),
            reverse("medicine_detail", args=[self.listing.product_id]),
            reverse("pharmacy_detail", args=[self.pharmacy.slug]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "10 available")
                self.assertNotContains(response, "10 currently available")

    def test_cart_does_not_disclose_remaining_shop_stock(self):
        self.client.force_login(self.customer)
        CartItem.objects.create(customer=self.customer, listing=self.listing, quantity=1)
        response = self.client.get(reverse("cart_detail"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "10 currently available")

    def test_unapproved_pharmacy_does_not_appear_publicly(self):
        self.pharmacy.verification_status = Pharmacy.VerificationStatus.PENDING
        self.pharmacy.save()
        response = self.client.get(reverse("medicine_search"))
        self.assertNotContains(response, "DEMO Verified Pharmacy")

    def test_checkout_reserves_stock_and_creates_pending_request(self):
        self.client.force_login(self.customer)
        CartItem.objects.create(customer=self.customer, listing=self.listing, quantity=2)
        response = self.client.post(reverse("checkout", args=[self.pharmacy.pk]), {"fulfilment": "pickup", "payment_method": "pay_at_store", "delivery_address": "", "customer_note": ""}, follow=True)
        self.assertEqual(response.status_code, 200)
        order = MarketplaceOrder.objects.get(customer=self.customer)
        self.listing.refresh_from_db()
        self.assertEqual(order.status, MarketplaceOrder.Status.PENDING)
        self.assertEqual(order.total, Decimal("30.00"))
        self.assertEqual(self.listing.available_quantity, 10)
        self.assertEqual(self.listing.reserved_quantity, 2)
        self.assertFalse(CartItem.objects.filter(customer=self.customer).exists())
        self.assertEqual(order.payment_method, MarketplaceOrder.PaymentMethod.PAY_AT_STORE)
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PENDING)
        self.assertEqual(response.redirect_chain[-1][0], reverse("order_detail", kwargs={"reference": order.reference}))

    def test_delivery_checkout_uses_cash_on_delivery(self):
        self.client.force_login(self.customer)
        CartItem.objects.create(customer=self.customer, listing=self.listing, quantity=1)
        response = self.client.post(reverse("checkout", args=[self.pharmacy.pk]), {
            "fulfilment": "delivery", "payment_method": "cash_on_delivery",
            "delivery_address": "10 Demo Road, Sampletown", "customer_note": "",
        })
        self.assertEqual(response.status_code, 302)
        order = MarketplaceOrder.objects.get(customer=self.customer)
        self.assertEqual(order.payment_method, MarketplaceOrder.PaymentMethod.COD)
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PENDING)
        self.assertEqual(response["Location"], reverse("order_detail", kwargs={"reference": order.reference}))

    def test_pickup_checkout_does_not_require_payment_method(self):
        self.client.force_login(self.customer)
        CartItem.objects.create(customer=self.customer, listing=self.listing, quantity=1)
        response = self.client.post(reverse("checkout", args=[self.pharmacy.pk]), {
            "fulfilment": "pickup", "delivery_address": "", "customer_note": "",
        })
        self.assertEqual(response.status_code, 302)
        order = MarketplaceOrder.objects.get(customer=self.customer)
        self.assertEqual(order.fulfilment, MarketplaceOrder.Fulfilment.PICKUP)
        self.assertEqual(order.payment_method, MarketplaceOrder.PaymentMethod.PAY_AT_STORE)
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PENDING)

    def test_customer_cannot_cancel_a_verified_paid_order(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            payment_method=MarketplaceOrder.PaymentMethod.RAZORPAY,
            payment_status=MarketplaceOrder.PaymentStatus.PAID,
            subtotal=Decimal("15.00"), total=Decimal("15.00"),
        )
        self.client.force_login(self.customer)
        response = self.client.post(reverse("customer_cancel_order", args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("order_detail", kwargs={"reference": order.reference}))
        order.refresh_from_db()
        self.assertEqual(order.status, MarketplaceOrder.Status.PENDING)
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PAID)

    def test_online_order_cannot_be_accepted_until_payment_is_verified(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.DELIVERY,
            delivery_address="10 Demo Road", payment_method=MarketplaceOrder.PaymentMethod.RAZORPAY,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING,
            subtotal=Decimal("20.00"), delivery_fee=Decimal("0.00"), total=Decimal("20.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("retailer_order_status", args=[order.pk]), {"status": "accepted"}, follow=True)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, MarketplaceOrder.Status.PENDING)
        self.assertContains(response, "Online payment must be verified before this order can be accepted.")

        order.payment_status = MarketplaceOrder.PaymentStatus.PAID
        order.save(update_fields=["payment_status", "updated_at"])
        response = self.client.post(reverse("retailer_order_status", args=[order.pk]), {"status": "accepted"}, follow=True)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, MarketplaceOrder.Status.ACCEPTED)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_medmitra", RAZORPAY_KEY_SECRET="test_secret_only")
    def test_late_captured_razorpay_payment_is_flagged_for_manual_refund(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.DELIVERY,
            delivery_address="10 Demo Road", payment_method=MarketplaceOrder.PaymentMethod.RAZORPAY,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING, status=MarketplaceOrder.Status.CANCELLED,
            subtotal=Decimal("20.00"), delivery_fee=Decimal("0.00"), total=Decimal("20.00"),
        )
        order.gateway_order_id = "order_test_cancelled"
        order.save(update_fields=["gateway_order_id", "updated_at"])
        self.client.force_login(self.customer)
        payment_id = "pay_test_late123"
        signature = hmac.new(b"test_secret_only", b"order_test_cancelled|pay_test_late123", hashlib.sha256).hexdigest()
        with patch("marketplace.views._razorpay_api_request", return_value={
            "order_id": "order_test_cancelled", "amount": 2000, "currency": "INR", "status": "captured",
        }):
            response = self.client.post(reverse("razorpay_verify_payment", args=[order.reference]), {
                "razorpay_order_id": "order_test_cancelled", "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        order.refresh_from_db()
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PAID)
        self.assertEqual(order.status, MarketplaceOrder.Status.REFUND_PENDING)
        self.assertIn("manual review", order.payment_review_note)

    def test_qr_payment_proof_is_private_and_needs_review(self):
        # Public QR belongs to the pharmacy/platform; customer proof must be private.
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
        )
        config = MarketplacePaymentSettings.objects.create(
            display_name="SBI Pay demo QR", upi_id="medmitra-demo@example.test",
            qr_image=SimpleUploadedFile("demo-qr.png", png_bytes, content_type="image/png"),
            is_active=True,
        )
        self.client.force_login(self.customer)
        CartItem.objects.create(customer=self.customer, listing=self.listing, quantity=1)
        checkout_response = self.client.post(reverse("checkout", args=[self.pharmacy.pk]), {
            "fulfilment": "delivery", "payment_method": "sbi_qr",
            "delivery_address": "10 Demo Road, Sampletown", "customer_note": "",
        })
        self.assertEqual(checkout_response.status_code, 302)
        order = MarketplaceOrder.objects.get(customer=self.customer)
        self.assertEqual(order.payment_method, MarketplaceOrder.PaymentMethod.SBI_QR)

        proof = SimpleUploadedFile("sbi-receipt.pdf", b"%PDF-1.4\nDemo transfer receipt", content_type="application/pdf")
        proof_response = self.client.post(reverse("payment_proof_upload", args=[order.reference]), {
            "payment_proof": proof, "payment_reference": "UTR-DEMO-123456",
        })
        self.assertEqual(proof_response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED)
        self.assertEqual(order.payment_reference, "UTR-DEMO-123456")
        self.assertTrue(order.payment_proof.storage.exists(order.payment_proof.name))
        self.assertNotIn(str(settings.MEDIA_ROOT), str(order.payment_proof.path))

        self.client.force_login(self.other)
        denied = self.client.get(reverse("payment_proof_download", args=[order.reference]))
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.owner)
        management_page = self.client.get(reverse("order_detail", kwargs={"reference": order.reference}))
        self.assertEqual(management_page.status_code, 200)
        self.assertContains(management_page, "Manage this order")
        self.assertContains(management_page, "Review payment proof")
        self.assertContains(management_page, "Verify payment received")
        self.assertContains(management_page, "Reject proof")
        download = self.client.get(reverse("payment_proof_download", args=[order.reference]))
        self.assertEqual(download.status_code, 200)
        approve = self.client.post(reverse("payment_proof_review", args=[order.reference]), {"decision": "approve", "note": "Transfer verified in account"})
        self.assertEqual(approve.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PAID)
        self.assertEqual(order.payment_verified_by_id, self.owner.pk)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_medmitra", RAZORPAY_KEY_SECRET="test_secret_only")
    def test_razorpay_payment_is_verified_server_side(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.DELIVERY,
            delivery_address="10 Demo Road", payment_method=MarketplaceOrder.PaymentMethod.RAZORPAY,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING,
            subtotal=Decimal("20.00"), delivery_fee=Decimal("0.00"), total=Decimal("20.00"),
        )
        self.client.force_login(self.customer)
        with patch("marketplace.views._razorpay_api_request") as api_call:
            api_call.return_value = {"id": "order_test123"}
            created = self.client.post(reverse("razorpay_create_order", args=[order.reference]))
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["order_id"], "order_test123")
            order.refresh_from_db()
            self.assertEqual(order.gateway_order_id, "order_test123")

            api_call.return_value = {"order_id": "order_test123", "amount": 2000, "currency": "INR", "status": "captured"}
            payment_id = "pay_test123"
            signature = hmac.new(b"test_secret_only", b"order_test123|pay_test123", hashlib.sha256).hexdigest()
            verified = self.client.post(reverse("razorpay_verify_payment", args=[order.reference]), {
                "razorpay_order_id": "order_test123", "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            })
            self.assertEqual(verified.status_code, 200)
            self.assertTrue(verified.json()["ok"])
            order.refresh_from_db()
            self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PAID)
            self.assertEqual(order.gateway_payment_id, payment_id)

    def _make_prescription(self, owner=None, requested_medicines="", preferred_pincode=""):
        return Prescription.objects.create(
            owner=owner or self.customer,
            file=SimpleUploadedFile("prescription.pdf", b"%PDF-1.4 test document", content_type="application/pdf"),
            original_filename="prescription.pdf",
            requested_medicines=requested_medicines,
            preferred_pincode=preferred_pincode,
        )

    def test_prescription_match_requires_one_pharmacy_for_every_typed_medicine(self):
        second = MedicineProduct.objects.create(
            brand_name="Vitamin C", generic_name="ascorbic acid", strength="500 mg",
            dosage_form="tablet", category=self.listing.product.category,
        )
        PharmacyListing.objects.create(
            pharmacy=self.pharmacy, product=second, mrp=Decimal("40.00"),
            selling_price=Decimal("32.00"), available_quantity=5,
        )
        prescription = self._make_prescription(
            requested_medicines="DEMO Paracetamol 500 mg\nVitamin C 500 mg",
            preferred_pincode=self.pharmacy.pincode,
        )
        self.client.force_login(self.customer)
        response = self.client.get(reverse("prescriptions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lists all 2 requested medicines")
        self.assertContains(response, "Indicative total for one of each")
        self.assertContains(response, self.pharmacy.name)
        self.assertEqual(len(response.context["prescriptions"][0].matching_pharmacies), 1)

    def test_prescription_callback_request_is_saved_for_admin_follow_up(self):
        prescription = self._make_prescription()
        self.client.force_login(self.customer)
        response = self.client.post(reverse("prescription_request_call", args=[prescription.pk]), {"callback_phone": "+91 98765 43210"})
        self.assertEqual(response.status_code, 302)
        prescription.refresh_from_db()
        self.assertTrue(prescription.callback_requested)
        self.assertEqual(prescription.callback_phone, "+91 98765 43210")
        self.assertTrue(MarketplaceAuditLog.objects.filter(action="prescription_callback_requested", object_id=str(prescription.pk)).exists())

    def test_customer_can_remove_unlinked_prescription(self):
        prescription = self._make_prescription()
        self.client.force_login(self.customer)
        response = self.client.post(reverse("prescription_delete", args=[prescription.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Prescription.objects.filter(pk=prescription.pk).exists())

    def test_customer_cannot_remove_prescription_linked_to_order(self):
        prescription = self._make_prescription()
        MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy, prescription=prescription,
            subtotal=Decimal("0.00"), total=Decimal("0.00"),
        )
        self.client.force_login(self.customer)
        response = self.client.post(reverse("prescription_delete", args=[prescription.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Prescription.objects.filter(pk=prescription.pk).exists())
        self.assertContains(response, "linked to an order and cannot be removed")

    def test_cod_order_can_be_accepted_before_payment_collection(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.DELIVERY, delivery_address="10 Demo Road",
            payment_method=MarketplaceOrder.PaymentMethod.COD,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING,
            subtotal=Decimal("15.00"), total=Decimal("15.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("retailer_order_status", args=[order.pk]), {"status": "accepted"}, follow=True)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, MarketplaceOrder.Status.ACCEPTED)
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PENDING)

    def test_order_receipt_pdf_download_is_private_and_valid_pdf(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            payment_method=MarketplaceOrder.PaymentMethod.RAZORPAY,
            payment_status=MarketplaceOrder.PaymentStatus.PAID,
            payment_verified_at=timezone.now(), subtotal=Decimal("15.00"), total=Decimal("15.00"),
        )
        MarketplaceOrderItem.objects.create(
            order=order, listing=self.listing, product_name_snapshot="DEMO Paracetamol 500 mg",
            quantity=1, unit_price=Decimal("15.00"), mrp_snapshot=Decimal("20.00"),
        )
        self.client.force_login(self.customer)
        response = self.client.get(reverse("order_receipt_pdf", kwargs={"reference": order.reference}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(b"%PDF", response.content[:8])
        self.assertIn("attachment", response["Content-Disposition"])

        self.client.force_login(self.other)
        denied = self.client.get(reverse("order_receipt_pdf", kwargs={"reference": order.reference}))
        self.assertEqual(denied.status_code, 403)

    def test_order_tracker_records_cash_and_renders_payment_receipt(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            status=MarketplaceOrder.Status.READY,
            fulfilment=MarketplaceOrder.Fulfilment.PICKUP,
            subtotal=Decimal("15.00"), total=Decimal("15.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("order_detail", kwargs={"reference": order.reference}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Track your order")
        self.assertContains(response, "Mark cash collected")
        response = self.client.post(reverse("retailer_mark_payment_collected", args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.COLLECTED)
        self.assertEqual(order.payment_collected_by_id, self.owner.pk)
        self.client.force_login(self.customer)
        response = self.client.get(reverse("order_detail", kwargs={"reference": order.reference}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MedMitra Payment Receipt")
        self.assertContains(response, "Cash collected")

    def test_stock_is_consumed_only_when_order_is_completed(self):
        order = MarketplaceOrder.objects.create(customer=self.customer, pharmacy=self.pharmacy, subtotal=Decimal("30.00"), total=Decimal("30.00"))
        MarketplaceOrderItem.objects.create(order=order, listing=self.listing, product_name_snapshot=str(self.listing.product), quantity=2, unit_price=Decimal("15.00"), mrp_snapshot=Decimal("20.00"))
        self.listing.reserved_quantity = 2
        self.listing.save()
        _transition_order(order, MarketplaceOrder.Status.ACCEPTED, self.owner)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.available_quantity, 10)
        self.assertEqual(self.listing.reserved_quantity, 2)
        _transition_order(order, MarketplaceOrder.Status.PROCESSING, self.owner)
        _transition_order(order, MarketplaceOrder.Status.READY, self.owner)
        _transition_order(order, MarketplaceOrder.Status.COMPLETED, self.owner)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.available_quantity, 8)
        self.assertEqual(self.listing.reserved_quantity, 0)
        self.assertTrue(MarketplaceAuditLog.objects.filter(action="order_status_changed", object_id=str(order.pk)).exists())

    def test_user_cannot_edit_other_pharmacy_listing(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("retailer_listing_edit", args=[self.listing.pk]))
        self.assertEqual(response.status_code, 403)

    def test_non_staff_cannot_open_platform_admin_dashboard(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("marketplace_admin_dashboard"))
        self.assertEqual(response.status_code, 302)


    def test_homepage_renders_requested_commerce_sections(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shop by Category")
        self.assertContains(response, "New Launches")
        self.assertContains(response, "Trending Near You")
        self.assertContains(response, "MedMitra Plus is coming soon")
        self.assertContains(response, "Mintop Shampoo +")
        self.assertNotContains(response, "Sample catalogue")
        self.assertContains(response, "Health Must Haves")
        self.assertContains(response, "Top selling")
        self.assertContains(response, "Trending")
        self.assertContains(response, "Top discounts")
        self.assertContains(response, "Pain relief")

    def test_homepage_section_title_is_admin_editable(self):
        section = HomepageSectionSetting.objects.get(key=HomepageSectionSetting.SectionKey.DIFFERENCE)
        section.title = "A clearer way to find care"
        section.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "A clearer way to find care")
        self.assertNotContains(response, "Why choose us?")

    def test_admin_can_manage_homepage_image_content_models(self):
        HomepageCategoryTile.objects.get_or_create(name="Admin test category", defaults={"icon": "bi-heart"})
        self.assertTrue(HomepageCategoryTile.objects.filter(name="Admin test category").exists())
        HomepageShowcaseProduct.objects.create(section=HomepageShowcaseProduct.Section.NEW_LAUNCHES, name="Admin test product", is_sample=True)
        HomepageMembershipBanner.objects.create(title="Admin test membership banner")
        self.assertTrue(HomepageMembershipBanner.objects.filter(title="Admin test membership banner").exists())
        # Image strip model intentionally requires an image; its admin upload workflow is exercised with real media in manual QA.


    def test_pickup_order_can_submit_qr_proof_using_pharmacy_upi_details(self):
        self.pharmacy.upi_id = "demo-shop@upi"
        self.pharmacy.save(update_fields=["upi_id", "updated_at"])
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.PICKUP,
            payment_method=MarketplaceOrder.PaymentMethod.PAY_AT_STORE,
            subtotal=Decimal("15.00"), total=Decimal("15.00"),
        )
        self.client.force_login(self.customer)
        response = self.client.get(reverse("order_detail", kwargs={"reference": order.reference}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "demo-shop@upi")
        self.assertContains(response, "Upload payment proof")
        proof = SimpleUploadedFile("pickup-proof.pdf", b"%PDF-1.4\nDemo pickup transfer", content_type="application/pdf")
        uploaded = self.client.post(reverse("payment_proof_upload", args=[order.reference]), {
            "payment_proof": proof, "payment_reference": "UTR-PICKUP-123",
        })
        self.assertEqual(uploaded.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_method, MarketplaceOrder.PaymentMethod.SBI_QR)
        self.assertEqual(order.payment_status, MarketplaceOrder.PaymentStatus.PROOF_SUBMITTED)

    def test_pickup_order_with_configured_qr_cannot_be_accepted_unpaid(self):
        self.pharmacy.upi_id = "demo-shop@upi"
        self.pharmacy.save(update_fields=["upi_id", "updated_at"])
        order = MarketplaceOrder.objects.create(
            customer=self.customer, pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.PICKUP,
            payment_method=MarketplaceOrder.PaymentMethod.PAY_AT_STORE,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING,
            subtotal=Decimal("15.00"), total=Decimal("15.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("retailer_order_status", args=[order.pk]), {"status": "accepted"}, follow=True)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, MarketplaceOrder.Status.PENDING)
        self.assertContains(response, "upload payment proof")

    def test_pharmacy_payment_details_form_requires_complete_bank_details(self):
        form = PharmacyPaymentDetailsForm({"bank_name": "Sample Bank"}, instance=self.pharmacy)
        self.assertFalse(form.is_valid())
        self.assertIn("bank_account_name", form.errors)
        self.assertIn("bank_account_number", form.errors)
        self.assertIn("bank_ifsc_code", form.errors)
        valid = PharmacyPaymentDetailsForm({"upi_id": "store@upi"}, instance=self.pharmacy)
        self.assertTrue(valid.is_valid(), valid.errors)

    def test_retailer_stat_cards_link_to_filtered_inventory_and_orders(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("retailer_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "stock=low")
        self.assertContains(response, "stock=out")
        self.assertContains(response, "stock=near_expiry")
        self.assertContains(response, "status=pending")
        self.assertNotContains(response, "View listings")
        self.assertNotContains(response, "Review stock")
        self.assertNotContains(response, "stat-card-cta")

    def test_mobile_navigation_has_home_option(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Mobile navigation"')
        self.assertContains(response, "MedMitra homepage")

    def test_customer_can_add_public_medicine_listing_to_cart(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse("cart_add", args=[self.listing.pk]), {"quantity": "1"}, follow=True)
        self.assertEqual(response.status_code, 200)
        item = CartItem.objects.get(customer=self.customer, listing=self.listing)
        self.assertEqual(item.quantity, 1)

    def test_retailer_stock_metric_filters_match_dashboard_counts(self):
        from datetime import timedelta
        from django.utils import timezone

        low_product = MedicineProduct.objects.create(
            brand_name="DEMO Low Stock Item", strength="10 mg", dosage_form="tablet",
            category=self.listing.product.category,
        )
        out_product = MedicineProduct.objects.create(
            brand_name="DEMO Out Stock Item", strength="20 mg", dosage_form="tablet",
            category=self.listing.product.category,
        )
        expired_product = MedicineProduct.objects.create(
            brand_name="DEMO Expired Item", strength="30 mg", dosage_form="tablet",
            category=self.listing.product.category,
        )
        low = PharmacyListing.objects.create(
            pharmacy=self.pharmacy, product=low_product, mrp=Decimal("20.00"),
            selling_price=Decimal("15.00"), available_quantity=5, reserved_quantity=1,
        )
        out = PharmacyListing.objects.create(
            pharmacy=self.pharmacy, product=out_product, mrp=Decimal("20.00"),
            selling_price=Decimal("15.00"), available_quantity=2, reserved_quantity=2,
        )
        expired = PharmacyListing.objects.create(
            pharmacy=self.pharmacy, product=expired_product, mrp=Decimal("20.00"),
            selling_price=Decimal("15.00"), available_quantity=4,
            expiry_date=timezone.localdate() - timedelta(days=1),
        )
        self.client.force_login(self.owner)
        dashboard = self.client.get(reverse("retailer_dashboard"), {"pharmacy": self.pharmacy.pk})
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context["low_stock_count"], 1)
        self.assertEqual(dashboard.context["out_of_stock_count"], 1)
        self.assertEqual(dashboard.context["expired_stock_count"], 1)
        low_page = self.client.get(reverse("retailer_listings"), {"pharmacy": self.pharmacy.pk, "stock": "low"})
        out_page = self.client.get(reverse("retailer_listings"), {"pharmacy": self.pharmacy.pk, "stock": "out"})
        expired_page = self.client.get(reverse("retailer_listings"), {"pharmacy": self.pharmacy.pk, "stock": "expired"})
        self.assertEqual(list(low_page.context["listings"].values_list("pk", flat=True)), [low.pk])
        self.assertEqual(list(out_page.context["listings"].values_list("pk", flat=True)), [out.pk])
        self.assertEqual(list(expired_page.context["listings"].values_list("pk", flat=True)), [expired.pk])

    def test_counter_sale_sells_multiple_store_listings_and_receipt_is_public(self):
        category = self.listing.product.category
        second_product = MedicineProduct.objects.create(
            brand_name="DEMO Vitamin C", generic_name="Ascorbic acid", strength="250 mg",
            dosage_form="tablet", category=category,
        )
        second_listing = PharmacyListing.objects.create(
            pharmacy=self.pharmacy, product=second_product,
            mrp=Decimal("50.00"), selling_price=Decimal("40.00"), available_quantity=5,
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("retailer_counter_sale"), {"pharmacy": self.pharmacy.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add another medicine")
        response = self.client.post(reverse("retailer_counter_sale"), {
            "pharmacy_id": str(self.pharmacy.pk),
            "customer_name": "Walk-in Demo",
            "payment_method": "upi",
            "listing_id": [str(self.listing.pk), str(second_listing.pk)],
            "quantity": ["2", "3"],
        })
        self.assertEqual(response.status_code, 302)
        sale = PharmacyCounterSale.objects.get(pharmacy=self.pharmacy)
        self.assertEqual(sale.items.count(), 2)
        self.assertEqual(sale.total, Decimal("150.00"))
        self.listing.refresh_from_db()
        second_listing.refresh_from_db()
        self.assertEqual(self.listing.available_quantity, 8)
        self.assertEqual(second_listing.available_quantity, 2)
        self.client.logout()
        receipt = self.client.get(reverse("counter_sale_receipt", kwargs={"token": sale.public_token}))
        self.assertEqual(receipt.status_code, 200)
        self.assertContains(receipt, sale.receipt_number)
        self.assertContains(receipt, "DEMO Vitamin C")
        self.assertContains(receipt, "₹150.00")
        self.assertEqual(receipt["X-Robots-Tag"], "noindex, nofollow")


    def test_retailer_order_detail_exposes_accept_reject_and_management_controls(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer,
            pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.DELIVERY,
            delivery_address="10 Demo Street, Sampletown",
            payment_method=MarketplaceOrder.PaymentMethod.COD,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING,
            subtotal=Decimal("15.00"), delivery_fee=Decimal("5.00"), total=Decimal("20.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("order_detail", kwargs={"reference": order.reference}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manage this order")
        self.assertContains(response, "Accept order")
        self.assertContains(response, "Reject order")
        self.assertContains(response, 'name="return_to" value="detail"')

    def test_retailer_order_action_from_detail_returns_to_same_order(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer,
            pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.DELIVERY,
            delivery_address="10 Demo Street, Sampletown",
            payment_method=MarketplaceOrder.PaymentMethod.COD,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING,
            subtotal=Decimal("15.00"), delivery_fee=Decimal("5.00"), total=Decimal("20.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("retailer_order_status", args=[order.pk]),
            {"status": MarketplaceOrder.Status.ACCEPTED, "return_to": "detail"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("order_detail", kwargs={"reference": order.reference}))
        order.refresh_from_db()
        self.assertEqual(order.status, MarketplaceOrder.Status.ACCEPTED)
        detail = self.client.get(reverse("order_detail", kwargs={"reference": order.reference}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Start processing")

    def test_unpaid_online_order_detail_explains_payment_gate_and_hides_accept(self):
        order = MarketplaceOrder.objects.create(
            customer=self.customer,
            pharmacy=self.pharmacy,
            fulfilment=MarketplaceOrder.Fulfilment.DELIVERY,
            delivery_address="10 Demo Street, Sampletown",
            payment_method=MarketplaceOrder.PaymentMethod.RAZORPAY,
            payment_status=MarketplaceOrder.PaymentStatus.PENDING,
            subtotal=Decimal("15.00"), delivery_fee=Decimal("5.00"), total=Decimal("20.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("order_detail", kwargs={"reference": order.reference}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Online payment must be verified before this order can be accepted.")
        self.assertNotContains(response, 'value="accepted" class="btn btn-primary rounded-pill"')
        self.assertContains(response, "Reject order")


class PrivateMediaProtectionTests(TestCase):
    def test_private_prescription_directory_is_not_served_as_public_media(self):
        request = RequestFactory().get("/media/private_prescriptions/user_1/sample.pdf")
        with self.assertRaises(Http404):
            safe_development_media(request, "private_prescriptions/user_1/sample.pdf")

    def test_parent_directory_traversal_is_rejected(self):
        request = RequestFactory().get("/media/../private_prescriptions/sample.pdf")
        with self.assertRaises(Http404):
            safe_development_media(request, "../private_prescriptions/sample.pdf")
