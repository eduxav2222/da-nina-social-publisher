# Da Nina Social Publisher

Dedicated, isolated social-publishing bridge for Da Nina Italian Restaurant.

## Purpose

This repository allows an approved Da Nina image and caption to be published to the restaurant's Instagram and Facebook Page through Meta Graph API after explicit user approval.

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

The request must also contain a caption, an image path or public image URL, and at least one target (`instagram` or `facebook`).

## Public images

Images created for automated publishing are stored under `public/`. The workflow builds an immutable `raw.githubusercontent.com` URL using the exact commit SHA so Meta can retrieve the approved image over HTTPS.

## Required GitHub Actions secret

Create exactly one repository secret:

`META_ACCESS_TOKEN`

Store the Da Nina Meta system-user access token there. Never put the token in source code, JSON request files, issues, README files, or chat messages.

GitHub path:

`Settings → Secrets and variables → Actions → New repository secret`

## Meta assets

Non-secret Meta asset IDs and the Graph API version are stored in `config/da_nina.json`.

## Publishing flow

1. Create/finalize the social image and caption.
2. Show the preview to the user.
3. Wait for explicit approval.
4. Store the approved image under `public/`.
5. Add one new approved request JSON under `publish/requests/`.
6. GitHub Actions validates the safety gate, verifies that the image is publicly reachable, checks Meta access, and publishes to the requested network(s).
7. The workflow returns the Meta publication IDs in its log.

## Files

- `.github/workflows/publish-social.yml` — guarded GitHub Actions publisher.
- `scripts/publish_social.py` — Meta Graph API publishing logic.
- `config/da_nina.json` — non-secret Page/Instagram IDs and API version.
- `examples/request.example.json` — request format example; this folder never triggers publishing.
- `public/` — public approved social assets.
- `publish/requests/` — live publication requests. Adding a valid request here triggers the workflow.

## Important

There is no atomic cross-platform transaction between Instagram and Facebook. If one platform publishes successfully and the other platform returns an API error, the successful platform can remain live while the failed platform is reported in the workflow log.
