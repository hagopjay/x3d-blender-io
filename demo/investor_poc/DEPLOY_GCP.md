# GCP Static Deployment

This technical-preview bundle is static-hosting friendly. The simplest Google Cloud deployment target is a Cloud Storage bucket fronted by a load balancer or served directly for preview use.

## Bundle

The deploy root is this directory:

- `index.html`
- `styles.css`
- `app.js`
- `demo_manifest.json`
- `single_inline_import_report.json`
- `multi_inline_import_report.json`
- `direct_x3d.html`
- `gltf_inline.html`
- `gltf_multi_inline.html`
- `blender_modern_poc.x3d`
- `xite_gltf_inline_poc.x3d`
- `xite_gltf_multi_inline_poc.x3d`
- `blender_scene.glb`
- `blender_scene_alt.glb`
- `textures/`
- `x_ite/`

Keep the relative layout intact.

## Option 1: Cloud Storage Website Hosting

1. Create a bucket:
   `gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=us-central1`
2. Make objects readable for preview use:
   `gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME --member=allUsers --role=roles/storage.objectViewer`
3. Sync the bundle:
   `gcloud storage rsync -r . gs://YOUR_BUCKET_NAME`
4. Set website config:
   `gcloud storage buckets update gs://YOUR_BUCKET_NAME --web-main-page-suffix=index.html`

Result:

- `https://storage.googleapis.com/YOUR_BUCKET_NAME/index.html`

## Option 2: Cloud Storage + HTTPS Load Balancer

Use this when you want a cleaner preview URL and TLS on a custom domain.

Recommended shape:

- Cloud Storage bucket as origin
- External HTTPS load balancer
- Cloud CDN enabled
- Managed certificate for custom domain

This keeps the preview static and cheap while preserving clean delivery for the X_ITE runtime and JSON assets.

## MIME Type Notes

Make sure these content types are correct if you upload via custom tooling:

- `.html` -> `text/html`
- `.css` -> `text/css`
- `.js` -> `application/javascript`
- `.json` -> `application/json`
- `.x3d` -> `model/x3d+xml` or `application/xml`
- `.glb` -> `model/gltf-binary`
- `.png` -> `image/png`

`gcloud storage rsync` usually handles common types well, but verify `.x3d` and `.glb`.

## Cache Guidance

For preview iteration:

- cache HTML lightly
- cache immutable runtime assets more aggressively

Practical split:

- `index.html`, viewer HTML, JSON reports: short cache
- `x_ite/`, `.glb`, `.png`: longer cache with versioned updates when regenerated

## Smoke Check After Deploy

Verify:

1. `index.html` loads
2. dashboard fetches `demo_manifest.json`
3. the embedded iframe loads `direct_x3d.html`
4. `x_ite` runtime loads correctly
5. `blender_modern_poc.x3d` renders
6. `xite_gltf_inline_poc.x3d` resolves `blender_scene.glb`
7. `xite_gltf_multi_inline_poc.x3d` resolves both `.glb` assets

## Recommended Next Packaging Step

If this preview is going to be shown repeatedly, add a small deploy script that:

- regenerates the Blender demo bundle
- validates required files exist
- syncs the directory to the target bucket
- prints the preview URL
