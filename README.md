# Da Nina Social Publisher

Dedicated, isolated social-publishing bridge for Da Nina Italian Restaurant.

## Purpose

This repository publishes user-approved Da Nina social content to the restaurant's Instagram Business account and official Facebook Page through Meta Graph API after explicit user approval.

The repository is intentionally separate from every other GitHub project.

## Cost and isolation rules

- Designed for $0 expected recurring cost.
- Uses only standard GitHub-hosted runners.
- Does not use paid runners, paid hosting, paid storage, or paid add-ons.
- No workflow or file in this repository modifies any other repository.
- Meta credentials must never be committed to this public repository.

## Safety gate

A request publishes live only when all three fields are present in a JSON file under `publish/requests/`:

```json
{
  "approved_by_user": true,
  "publish_mode": "live",
  "confirmation": "PUBLISH_DA_NINA"
}
```

The request must contain at least one target and the appropriate approved image asset(s). Feed targets also require an approved caption.

## Platform-specific image policy

For normal static promotional publishing, do not force one image file onto every placement. The standard automated formats are:

- Instagram Feed: **1080 × 1350 (4:5)**
- Facebook Feed: **1080 × 1080 (1:1)**
- Instagram Story: **1080 × 1920 (9:16)**
- Facebook Page Story: **1080 × 1920 (9:16)**

A single approved source artwork may be deterministically adapted into separate platform assets after the previews have been approved. The request's `platform_images` map routes each Meta target to the correct file. Instagram and Facebook Stories may share the same approved 9:16 file.

The older single `image_path` / `image_url` request format remains supported for compatibility, but new multi-platform posts should use platform-specific assets.

## Public images

Images created for automated publishing are stored under `public/`. After generation, the workflow records the exact commit containing those assets and builds `raw.githubusercontent.com` URLs from that commit so Meta can retrieve them over HTTPS.

## Required GitHub Actions secret

Create exactly one repository secret:

`META_ACCESS_TOKEN`

Store the Da Nina Meta system-user access token there. Never put the token in source code, JSON request files, issues, README files, logs, or chat messages.

GitHub path:

`Settings → Secrets and variables → Actions → New repository secret`

## Meta assets

Non-secret Meta asset IDs and the Graph API version are stored in `config/da_nina.json`.

## Publishing flow

1. Create/finalize the social artwork and caption.
2. Prepare placement-specific previews: Instagram 4:5, Facebook 1:1, and Stories 9:16 as applicable.
3. Show the previews to the user.
4. Wait for explicit approval.
5. Add one new approved request JSON under `publish/requests/`.
6. GitHub Actions creates the approved platform-specific assets under `public/` when the request specifies deterministic transforms.
7. The workflow validates the safety gate, verifies every target image is publicly reachable, checks Meta access, and routes the correct asset to each requested network/placement.
8. The workflow returns the Meta publication IDs in its log.

## Files

- `.github/workflows/publish-social.yml` — guarded GitHub Actions publisher.
- `scripts/prepare_image.py` — deterministic platform-specific image generation.
- `scripts/publish_social.py` — Meta Graph API publishing and target-to-image routing logic.
- `config/da_nina.json` — non-secret Page/Instagram IDs and API version.
- `examples/request.example.json` — current multi-platform request format example; this folder never triggers publishing.
- `public/` — public approved social assets.
- `publish/requests/` — live publication requests. Adding a valid request here triggers the workflow.

## Retry safety

There is no atomic cross-platform transaction between Instagram and Facebook. If one destination succeeds and another fails, retry only the failed destination so a successful feed post or Story is never duplicated.
