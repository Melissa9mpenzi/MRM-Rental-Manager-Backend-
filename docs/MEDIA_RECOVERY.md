# Recover property photos you uploaded from your laptop

When you first added properties, images were saved under `./uploads/...` on the API server. On Vercel that folder is **temporary**, so your real files were lost after deploy. The app was sometimes showing a **stock placeholder** — not your photos.

## Option A — Re-upload in the app (easiest)

1. Deploy latest backend + frontend.
2. Open each property on the web app.
3. Click **Re-upload your photo** and choose the same file from your laptop.
4. The URL in the database becomes `https://res.cloudinary.com/...` and stays permanent.

## Option B — Bulk restore from files on your PC

If you still have the original files (Downloads, Pictures, or an old `uploads` backup):

```bash
cd D:\MRM-Rental-Manager-Backend-
python -m app.utils.recover_property_photos_from_folder --list
```

Copy each file into the path shown, for example:

`D:\MRM-Rental-Manager-Backend-\uploads\properties\<filename>.jpg`

Then:

```bash
python -m app.utils.recover_property_photos_from_folder --apply
```

Requires `CLOUDINARY_*` in your `.env`.
