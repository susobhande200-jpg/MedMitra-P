# MedMitra checkout, payment and tracking setup

## Available checkout choices

- **Home delivery:** Cash on Delivery (COD) is always available. Razorpay is offered only when both `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` are configured. SBI Pay / UPI QR is offered only after an administrator uploads and activates a verified QR in Django Admin.
- **Store pickup:** Customers can submit a pickup order without selecting a payment method. MedMitra records the existing `pay_at_store` value internally for database compatibility, and the customer pays at the pharmacy counter when collecting the order.
- **QR payment proof:** Customers upload a JPG, JPEG, PNG, WebP or PDF transaction proof (maximum 5 MB) and may add a UTR/reference. Proof files are stored outside the public `MEDIA_ROOT`; only the customer, assigned pharmacy owner and superuser can download them. Uploading proof does not mark an order paid. The pharmacy owner/superuser must verify that funds arrived and approve the proof.
- **Razorpay:** The server creates provider orders, verifies the signed callback with HMAC-SHA256, fetches payment details from the provider API, and only records `paid` after a matching INR payment is captured. Razorpay secrets are read only from environment variables and are never rendered to the browser.

## Configure SBI Pay / UPI QR

1. Sign in to `/admin/` as a Django superuser.
2. Open **Marketplace → Payment settings (SBI Pay / UPI QR)**.
3. Add one configuration with the verified display name, optional UPI ID, QR image, clear payment instructions and `is_active` enabled.
4. Verify the payee/account independently before activating. The uploaded QR is public-facing; do not upload a customer's payment proof into this setting.

Only one active QR configuration is allowed by the model. If no active image is configured, the QR option is not offered at checkout.

## Configure Razorpay

Add the Razorpay credentials in a local `.env` or the host's secret environment configuration. Never commit real credentials:

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=your_test_secret
```

Use Razorpay **test-mode credentials** for development first. Restart Django after changing environment variables. The checkout option appears only when both values are present. A production payment integration still requires the merchant's own Razorpay account, approved credentials, webhook/operational monitoring and a real end-to-end payment test before going live.

## Order tracking and fulfillment

The order detail page shows pharmacy status events: request submitted, accepted, preparing, ready for pickup, out for delivery (delivery orders only), and completed. These are status updates, not live courier GPS tracking. Online orders with Razorpay or QR cannot be accepted before payment is verified. If an already-paid order is cancelled/rejected by the pharmacy, the order enters `refund_pending` and requires manual refund processing; this project does not automatically issue a gateway refund.

## Verification commands

Run from the folder containing `manage.py`:

```powershell
python manage.py migrate
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test marketplace
```

Before launch, test Razorpay in test mode, upload/approve/reject a QR proof using two accounts (customer + pharmacy owner), confirm pickup checkout works without a payment selection, and ensure private proof URLs are not publicly served.
