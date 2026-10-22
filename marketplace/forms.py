from django import forms
from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.validators import FileExtensionValidator

from .models import (
    Pharmacy, PharmacyListing, Prescription, CartItem, MarketplaceOrder,
    MedicineCategory, MedicineProduct, MarketplacePaymentSettings,
)


class PharmacyRegistrationForm(forms.ModelForm):
    class Meta:
        model = Pharmacy
        fields = [
            "name", "phone", "email", "address", "locality", "city", "state", "pincode",
            "latitude", "longitude", "licence_number", "licence_expiry", "pharmacist_name",
            "pharmacist_registration", "opening_time", "closing_time", "offers_delivery",
            "offers_pickup", "delivery_fee", "payment_qr_image", "upi_id",
            "bank_account_name", "bank_name", "bank_account_number", "bank_ifsc_code",
            "payment_instructions",
        ]
        widgets = {
            "licence_expiry": forms.DateInput(attrs={"type": "date"}),
            "opening_time": forms.TimeInput(attrs={"type": "time"}),
            "closing_time": forms.TimeInput(attrs={"type": "time"}),
            "latitude": forms.NumberInput(attrs={"step": "any", "placeholder": "Optional"}),
            "longitude": forms.NumberInput(attrs={"step": "any", "placeholder": "Optional"}),
            "offers_delivery": forms.CheckboxInput(),
            "offers_pickup": forms.CheckboxInput(),
            "payment_qr_image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-control"
            else:
                field.widget.attrs["class"] = "form-check-input"
        self.fields["name"].help_text = "Your store remains hidden from customers until an administrator verifies it."
        self.fields["payment_qr_image"].required = False
        self.fields["payment_qr_image"].label = "Store UPI / SBI Pay QR image (optional)"
        self.fields["payment_qr_image"].help_text = "Upload the QR that receives payments for this pharmacy. Customers see it only on orders for your store. Maximum 5 MB."
        self.fields["upi_id"].required = False
        self.fields["upi_id"].help_text = "Optional. Example: yourstore@upi"
        self.fields["bank_account_number"].help_text = "Optional. If bank transfer details are entered, all bank fields are required."
        self.fields["payment_instructions"].help_text = "Instructions shown on your order payment page."
        for required_field in ("licence_number", "licence_expiry", "pharmacist_name", "pharmacist_registration"):
            self.fields[required_field].required = True

    def clean_payment_qr_image(self):
        image = self.cleaned_data.get("payment_qr_image")
        if image and image.size > 5 * 1024 * 1024:
            raise ValidationError("Payment QR image must be 5 MB or smaller.")
        content_type = getattr(image, "content_type", "") if image else ""
        if image and content_type and content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValidationError("Upload a JPG, PNG, or WebP payment QR image.")
        return image

    def clean_pincode(self):
        value = self.cleaned_data["pincode"].strip()
        if not value.isdigit() or not 4 <= len(value) <= 10:
            raise ValidationError("Enter a valid postal / PIN code.")
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("delivery_fee") is not None and cleaned["delivery_fee"] < 0:
            self.add_error("delivery_fee", "Delivery fee cannot be negative.")
        if cleaned.get("opening_time") and cleaned.get("closing_time") and cleaned["opening_time"] == cleaned["closing_time"]:
            self.add_error("closing_time", "Opening and closing time cannot be the same.")
        if not cleaned.get("offers_delivery") and not cleaned.get("offers_pickup"):
            raise ValidationError("Enable at least one fulfilment option: delivery or pickup.")
        bank_fields = ("bank_account_name", "bank_name", "bank_account_number", "bank_ifsc_code")
        if any((cleaned.get(field) or "").strip() for field in bank_fields):
            for field in bank_fields:
                if not (cleaned.get(field) or "").strip():
                    self.add_error(field, "Complete all bank details if you want customers to pay by bank transfer.")
        return cleaned


class PharmacyPaymentDetailsForm(forms.ModelForm):
    class Meta:
        model = Pharmacy
        fields = ["payment_qr_image", "upi_id", "bank_account_name", "bank_name", "bank_account_number", "bank_ifsc_code", "payment_instructions"]
        widgets = {"payment_qr_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/jpeg,image/png,image/webp"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")
        self.fields["payment_qr_image"].help_text = "JPG, PNG or WebP; maximum 5 MB. A new upload replaces the old QR."
        self.fields["upi_id"].help_text = "Optional UPI ID for this pharmacy."
        self.fields["payment_instructions"].help_text = "Shown to customers on this store's order page."

    def clean_payment_qr_image(self):
        image = self.cleaned_data.get("payment_qr_image")
        if image and image.size > 5 * 1024 * 1024:
            raise ValidationError("Payment QR image must be 5 MB or smaller.")
        content_type = getattr(image, "content_type", "") if image else ""
        if image and content_type and content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValidationError("Upload a JPG, PNG, or WebP payment QR image.")
        return image

    def clean(self):
        cleaned = super().clean()
        bank_fields = ("bank_account_name", "bank_name", "bank_account_number", "bank_ifsc_code")
        if any((cleaned.get(field) or "").strip() for field in bank_fields):
            for field in bank_fields:
                if not (cleaned.get(field) or "").strip():
                    self.add_error(field, "Complete all bank details if you want customers to pay by bank transfer.")
        return cleaned


class ListingForm(forms.ModelForm):
    # A shop can select an existing catalogue item or add one inline when the
    # catalogue does not yet contain its medicine. No model migration is needed.
    product = forms.ModelChoiceField(
        queryset=MedicineProduct.objects.none(),
        required=False,
        empty_label="Choose a medicine from the catalogue",
        widget=forms.Select(attrs={"class": "form-select", "data-existing-product": "true"}),
        label="Existing catalogue medicine",
    )
    new_catalogue_product = forms.BooleanField(
        required=False,
        label="Add a medicine that is not in the catalogue",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "data-new-product-toggle": "true"}),
    )
    new_product_name = forms.CharField(
        required=False, max_length=160, label="Medicine / product name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Exact brand or product name"}),
    )
    new_generic_name = forms.CharField(
        required=False, max_length=160, label="Generic name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Generic name (optional)"}),
    )
    new_strength = forms.CharField(
        required=False, max_length=80, label="Strength",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 500 mg"}),
    )
    new_dosage_form = forms.ChoiceField(
        required=False, label="Dosage / product form",
        choices=[("", "Choose product form")] + list(MedicineProduct.DosageForm.choices),
        initial=MedicineProduct.DosageForm.TABLET,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    new_pack_size = forms.CharField(
        required=False, max_length=80, label="Pack size",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 10 tablets (optional)"}),
    )
    new_manufacturer = forms.CharField(
        required=False, max_length=160, label="Manufacturer",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Manufacturer (optional)"}),
    )
    new_category = forms.ModelChoiceField(
        queryset=MedicineCategory.objects.none(), required=False, label="Category",
        empty_label="Choose category (optional)", widget=forms.Select(attrs={"class": "form-select"}),
    )
    new_requires_prescription = forms.BooleanField(
        required=False, label="Prescription required",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    new_product_image = forms.ImageField(
        required=False, label="Catalogue image (optional)",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/jpeg,image/png,image/webp"}),
        help_text="JPG, PNG or WebP; maximum 5 MB.",
    )

    class Meta:
        model = PharmacyListing
        fields = ["product", "image", "mrp", "selling_price", "available_quantity", "batch_number", "expiry_date", "active"]
        widgets = {
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = MedicineProduct.objects.filter(active=True).order_by("brand_name", "strength")
        self.fields["new_category"].queryset = MedicineCategory.objects.filter(active=True).order_by("name")
        self.fields["image"].label = "Store-specific medicine image (optional)"
        self.fields["image"].help_text = "Shows on this pharmacy's listing; JPG, PNG or WebP, maximum 5 MB."
        # Place the existing item first, followed by an explicit new-item option,
        # then the listing's price, stock, image and publish controls.
        desired_order = [
            "product", "new_catalogue_product", "new_product_name", "new_generic_name",
            "new_strength", "new_dosage_form", "new_pack_size", "new_manufacturer",
            "new_category", "new_requires_prescription", "new_product_image",
            "image", "mrp", "selling_price", "available_quantity", "batch_number", "expiry_date", "active",
        ]
        self.order_fields(desired_order)
        for name, field in self.fields.items():
            if name in {"active", "new_catalogue_product", "new_requires_prescription"}:
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")

    def _get_validation_exclusions(self):
        excluded = super()._get_validation_exclusions()
        # During the add-new-product flow the view creates the catalogue product
        # transactionally after form validation, so the temporary None value on
        # the listing's required FK must not fail Model.clean_fields yet.
        if self.cleaned_data.get("new_catalogue_product"):
            excluded.add("product")
        return excluded

    def clean_image(self):
        return self._validate_image(self.cleaned_data.get("image"), "Medicine image")

    def clean_new_product_image(self):
        return self._validate_image(self.cleaned_data.get("new_product_image"), "Catalogue image")

    @staticmethod
    def _validate_image(image, label):
        if image and image.size > 5 * 1024 * 1024:
            raise ValidationError(f"{label} must be 5 MB or smaller.")
        content_type = getattr(image, "content_type", "") if image else ""
        if image and content_type and content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValidationError("Upload a JPG, PNG, or WebP image.")
        return image

    def clean(self):
        cleaned = super().clean()
        selected = cleaned.get("product")
        create_new = cleaned.get("new_catalogue_product")
        new_name = (cleaned.get("new_product_name") or "").strip()
        strength = (cleaned.get("new_strength") or "").strip()

        if create_new:
            if selected:
                self.add_error("product", "Choose an existing medicine OR add a new catalogue medicine, not both.")
            if not new_name:
                self.add_error("new_product_name", "Enter the medicine name to add it to the catalogue.")
            elif not selected:
                duplicate = MedicineProduct.objects.filter(brand_name__iexact=new_name, strength__iexact=strength).first()
                if duplicate:
                    if duplicate.active:
                        self.add_error("new_product_name", "This medicine is already in the catalogue. Select it from the existing-medicine list instead.")
                    else:
                        self.add_error("new_product_name", "This medicine is in the catalogue but inactive. Ask the MedMitra administrator to review it.")
            if not cleaned.get("new_dosage_form"):
                self.add_error("new_dosage_form", "Choose the medicine or product form.")
        else:
            if new_name:
                self.add_error("new_product_name", "Tick ‘Add a medicine that is not in the catalogue’ first.")
            if not selected:
                self.add_error("product", "Select a catalogue medicine or tick the option to add a new one.")

        mrp, selling_price = cleaned.get("mrp"), cleaned.get("selling_price")
        if mrp is not None and selling_price is not None and selling_price > mrp:
            self.add_error("selling_price", "Selling price cannot be higher than MRP.")
        if self.instance.pk and cleaned.get("available_quantity", 0) < self.instance.reserved_quantity:
            self.add_error("available_quantity", "Quantity cannot be lower than stock reserved for open orders.")
        expiry = cleaned.get("expiry_date")
        from django.utils import timezone
        if expiry and expiry < timezone.localdate():
            self.add_error("expiry_date", "Expired batches cannot be listed for sale.")
        return cleaned


class PrescriptionUploadForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ["file", "requested_medicines", "preferred_pincode", "customer_note"]
        widgets = {
            "customer_note": forms.TextInput(attrs={"class": "form-control", "maxlength": 240}),
            "requested_medicines": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "One medicine per line, e.g. Paracetamol 500 mg\nVitamin D3 60,000 IU"}),
            "preferred_pincode": forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric", "maxlength": 10, "placeholder": "Your area PIN code (optional)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs.update({"class": "form-control", "accept": ".jpg,.jpeg,.png,.pdf"})
        self.fields["requested_medicines"].help_text = "Optional but recommended: this lets MedMitra look for one pharmacy that lists every medicine in your basket. It does not use OCR to read the uploaded file."

    def clean_requested_medicines(self):
        value = self.cleaned_data.get("requested_medicines", "").strip()
        terms = [line.strip() for line in value.replace(";", "\n").splitlines() if line.strip()]
        if len(terms) > 20:
            raise ValidationError("Enter no more than 20 medicine names, one per line.")
        if any(len(term) > 100 for term in terms):
            raise ValidationError("Each medicine name must be 100 characters or fewer.")
        return "\n".join(terms)

    def clean_preferred_pincode(self):
        value = self.cleaned_data.get("preferred_pincode", "").strip()
        if value and (not value.isdigit() or not 4 <= len(value) <= 10):
            raise ValidationError("Enter a valid PIN code or leave it blank.")
        return value

    def clean_file(self):
        file = self.cleaned_data["file"]
        if file.size > 10 * 1024 * 1024:
            raise ValidationError("File is too large. Maximum allowed size is 10 MB.")
        ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
        if ext not in {"jpg", "jpeg", "png", "pdf"}:
            raise ValidationError("Upload a JPG, PNG, or PDF file.")
        content_type = getattr(file, "content_type", "")
        allowed = {"image/jpeg", "image/png", "application/pdf", "application/x-pdf", "image/pjpeg"}
        if content_type and content_type not in allowed:
            raise ValidationError("The uploaded file type does not match an allowed document type.")
        # Don't rely only on a filename or the client-supplied MIME type. Check basic file signatures.
        file.seek(0)
        signature = file.read(16)
        file.seek(0)
        valid_signature = {
            "jpg": signature.startswith(b"\xff\xd8\xff"),
            "jpeg": signature.startswith(b"\xff\xd8\xff"),
            "png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
            "pdf": signature.startswith(b"%PDF-"),
        }.get(ext, False)
        if not valid_signature:
            raise ValidationError("The file contents do not match the selected document format.")
        return file


class CartAddForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=50, initial=1, widget=forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 50}))


class CheckoutForm(forms.Form):
    fulfilment = forms.ChoiceField(choices=MarketplaceOrder.Fulfilment.choices, widget=forms.RadioSelect)
    # Optional at form level because store-pickup orders deliberately do not ask
    # for a payment choice at order placement. Delivery validates it in clean().
    payment_method = forms.ChoiceField(choices=MarketplaceOrder.PaymentMethod.choices, required=False, widget=forms.RadioSelect)
    prescription = forms.ModelChoiceField(queryset=Prescription.objects.none(), required=False, empty_label="Choose a prescription (if required)", widget=forms.Select(attrs={"class": "form-select"}))
    delivery_address = forms.CharField(required=False, max_length=300, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "House / street, locality, PIN code"}))
    customer_note = forms.CharField(required=False, max_length=300, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Optional instructions"}))

    def __init__(self, *args, customer=None, pharmacy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        self.pharmacy = pharmacy
        self.qr_settings = bool(
            (pharmacy and pharmacy.has_payment_destination) or MarketplacePaymentSettings.active_qr()
        )
        self.razorpay_enabled = bool(
            getattr(settings, "RAZORPAY_KEY_ID", "").strip()
            and getattr(settings, "RAZORPAY_KEY_SECRET", "").strip()
        )
        if customer is not None:
            self.fields["prescription"].queryset = Prescription.objects.filter(owner=customer, status__in=[Prescription.Status.PENDING, Prescription.Status.APPROVED]).order_by("-created_at")
        if pharmacy:
            choices = []
            if pharmacy.offers_pickup:
                choices.append((MarketplaceOrder.Fulfilment.PICKUP, "Collect from pharmacy"))
            if pharmacy.offers_delivery:
                choices.append((MarketplaceOrder.Fulfilment.DELIVERY, "Home delivery"))
            self.fields["fulfilment"].choices = choices
            if len(choices) == 1:
                self.fields["fulfilment"].initial = choices[0][0]
            elif not self.is_bound and not self.initial.get("fulfilment"):
                # Use pickup as the comfortable default when offered, so payment
                # controls are initially collapsed and no payment is forced.
                preferred_mode = MarketplaceOrder.Fulfilment.PICKUP if pharmacy.offers_pickup else MarketplaceOrder.Fulfilment.DELIVERY
                self.fields["fulfilment"].initial = preferred_mode

        payment_choices = [
            (MarketplaceOrder.PaymentMethod.COD, "Cash on delivery (COD)"),
            (MarketplaceOrder.PaymentMethod.PAY_AT_STORE, "Pay by pharmacy QR / bank transfer (pickup)"),
        ]
        if self.qr_settings:
            payment_choices.append((MarketplaceOrder.PaymentMethod.SBI_QR, "Pay by UPI / bank transfer and upload receipt"))
        if self.razorpay_enabled:
            payment_choices.append((MarketplaceOrder.PaymentMethod.RAZORPAY, "Online payment — Razorpay"))
        self.fields["payment_method"].choices = payment_choices

        initial_mode = self.data.get("fulfilment") or self.initial.get("fulfilment")
        if not initial_mode and pharmacy and self.fields["fulfilment"].initial:
            initial_mode = self.fields["fulfilment"].initial
        self.fields["payment_method"].initial = (
            MarketplaceOrder.PaymentMethod.COD
            if initial_mode == MarketplaceOrder.Fulfilment.DELIVERY
            else MarketplaceOrder.PaymentMethod.PAY_AT_STORE
        )

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("fulfilment")
        if self.pharmacy and mode == MarketplaceOrder.Fulfilment.DELIVERY:
            if not self.pharmacy.offers_delivery:
                self.add_error("fulfilment", "This pharmacy does not offer delivery.")
            if not cleaned.get("delivery_address", "").strip():
                self.add_error("delivery_address", "Enter a delivery address for home delivery.")
            allowed_delivery_methods = {MarketplaceOrder.PaymentMethod.COD}
            if self.qr_settings:
                allowed_delivery_methods.add(MarketplaceOrder.PaymentMethod.SBI_QR)
            if self.razorpay_enabled:
                allowed_delivery_methods.add(MarketplaceOrder.PaymentMethod.RAZORPAY)
            if cleaned.get("payment_method") not in allowed_delivery_methods:
                self.add_error("payment_method", "Choose COD or one of the available online payment options for home delivery.")
        elif self.pharmacy and mode == MarketplaceOrder.Fulfilment.PICKUP:
            if not self.pharmacy.offers_pickup:
                self.add_error("fulfilment", "This pharmacy does not offer pickup.")
            # Do not ask customers to choose a payment method for pickup. Keep a
            # legacy-compatible internal value so existing order records remain valid.
            cleaned["payment_method"] = MarketplaceOrder.PaymentMethod.PAY_AT_STORE
        return cleaned


class PaymentProofForm(forms.Form):
    payment_proof = forms.FileField(
        label="Payment screenshot or receipt",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "pdf"])],
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/jpeg,image/png,image/webp,application/pdf"}),
        help_text="JPG, PNG, WebP or PDF; maximum 5 MB.",
    )
    payment_reference = forms.CharField(
        required=False, max_length=100, label="UTR / transaction reference (optional)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter UPI transaction reference if available", "autocomplete": "off"}),
    )

    def clean_payment_proof(self):
        file = self.cleaned_data["payment_proof"]
        if file.size > 5 * 1024 * 1024:
            raise ValidationError("Payment proof must be 5 MB or smaller.")
        ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
        signature = file.read(16)
        file.seek(0)
        valid = {
            "jpg": signature.startswith(b"\xff\xd8\xff"),
            "jpeg": signature.startswith(b"\xff\xd8\xff"),
            "png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
            "pdf": signature.startswith(b"%PDF-"),
            "webp": len(signature) >= 12 and signature[:4] == b"RIFF" and signature[8:12] == b"WEBP",
        }.get(ext, False)
        if not valid:
            raise ValidationError("The uploaded file contents do not match a supported image or PDF.")
        return file
