# MedMitra homepage content guide

After extracting the project, activating `.venv`, installing `requirements.txt`, and running `python manage.py migrate`, sign in at `/admin/` with a Django superuser.

All new homepage content screens below are restricted to superusers. Shop owners continue to manage their own medicine listings from the retailer workspace.

## Homepage sections and headings

Open **Marketplace → Homepage section headings** to edit section eyebrows, headings, descriptions, ordering, or turn a section off. The “THE MEDMITRA DIFFERENCE / Why choose us?” section is no longer hard-coded: the administrator can rename it, edit its intro, or hide it. Use **Homepage trust metrics** to manage its individual benefit cards.

## Categories

Open **Homepage category tiles** to edit the 16 default health categories, upload a category image if needed, choose an icon, adjust order, disable a tile, or set a destination URL. Corresponding medicine categories are seeded so an administrator can assign catalogue products to the right category in **Medicine categories**.

## Product cards and medicine photos

Open **Homepage featured products** to manage “New Launches” and “Trending Near You” cards. Administrators can update product text, upload images, edit displayed prices and links, and publish/unpublish a card. Imported sample cards display a visible **Sample catalogue** marker. Verify the price against current supplier/store information, replace it with a current approved listing or deactivate it, and turn off the sample flag before representing it as a live offer.

There are two photo-upload paths for real medicine catalogue content:

- **Admin:** Marketplace → Medicine products → upload the shared catalogue image. This image appears as a fallback where a pharmacy listing does not have its own image.
- **Shop owner:** Retailer workspace → My listings → add/edit a listing → upload its image. This store-specific image takes priority on search results and live local-pharmacy cards.

Images are optional. If no image has been uploaded, MedMitra displays a designed medicine placeholder rather than a broken image.

## Offers and wide horizontal banners

- **Homepage promotions / advertisements** creates image promotions with title, optional subtitle, CTA, destination and optional start/end schedule. These appear in the offer carousel below the hero.
- **Homepage image-only banners** creates the lower horizontal scroll rail. Upload an image and alternative text; no title or description is displayed. A destination URL and schedule are optional.
- **Homepage membership banners** controls the wide MedMitra Plus “coming soon” banner. Edit the wording, optional image, CTA and visibility.

## Customer reviews

Open **Homepage customer reviews** to enter genuine MedMitra reviews that you are authorised to publish. The public site only renders reviews marked **Published**. Do not import testimonials from another service or present sample copy as a real MedMitra review.

## Run locally

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver
```

Use `http://127.0.0.1:8000/` (HTTP, not HTTPS) for local development. Uploaded media should be stored on persistent media storage in production; files in a temporary local container may not survive redeployment.
