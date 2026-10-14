# HousePanel Releases

## Deployment and release records

Merging a reviewed PR into `main` continues to deploy automatically after the
push CI succeeds. An annotated Git tag and a GitHub release record a verified
production deployment. Tags do not trigger another build or deployment.

The release agent deploys the exact tested image archives using immutable
registry digests. It checks rollout health, restarts, panel connectivity, and
delivery from every poller. Ring must remain at zero replicas.

## Versions

Use `vMAJOR.MINOR.PATCH` tags. Start with `v0.1.0`; during the initial `0.x`
series, increase MINOR for compatibility changes or new functionality and
PATCH for compatible fixes. At `1.0.0` and later, increase MAJOR for breaking
contracts, MINOR for compatible features, and PATCH for compatible fixes.

Release tags are immutable. Never move an existing version to another commit.
A correction or rollback gets a new version. Record configuration or firmware
changes separately if they are not included in the service image bundle.

## Ship and verify

1. Open a PR with focused tests, typing checks, and memory/lifecycle coverage
   when relevant. Leave it open for the user's review. Consult the user before
   exceeding two Codex review rounds.
2. After the user merges, require successful **push** CI for that exact main
   commit, including `Quality Gate` and the `housepanel-release` artifact.
   Passing PR CI alone does not qualify an image for production.
3. Allow the five-minute release timer to run, or start the existing agent with
   `systemctl --user start housepanel-release.service`. Do not bypass its checks
   with locally rebuilt images or direct deployment edits.
4. Check `~/.local/state/housepanel-release/deployed.json`, the service journal,
   and the associated GitHub deployment status. Require a successful status for
   the exact deployed SHA. A failure marker must be investigated before retrying.
   Pin the deployment record using the next section before preparing evidence.
5. Capture a post-deployment memory baseline after all services are ready and
   every poller has delivered. Include UTC time, pod UID, container ID, image
   digest, start time, restart count, process RSS, cgroup RSS/working set, thread
   count, and open file count. Preserve a startup baseline rather than hiding
   early growth behind a long warmup. Record any later settled baseline too.

The deployer's checkout can be on a different branch. Identify the release by
the verified deployment SHA, never by the checkout's `HEAD`.

## Pin the deployment

On the machine that runs the release agent, choose the next unused version and
capture the intended deployment **before** collecting the baseline or drafting
notes. Read the live marker once: the agent replaces it after each deployment.
The version below is an example. Review the captured SHA and deployment ID.

```sh
set -eu
REPO=kwehden/HousePanel
STATE="$HOME/.local/state/housepanel-release/deployed.json"
VERSION=${VERSION:-v0.1.0}
RELEASE_DIR="build/releases/$VERSION"
RECORD="$RELEASE_DIR/deployment.json"
mkdir -p "$RELEASE_DIR"
# Refuse to overwrite an existing release record.
(set -C; jq -e 'select(.status_reported == true)' "$STATE" > "$RECORD")
jq '{sha, run_id, deployment_id, time}' "$RECORD"
```

Keep this record unchanged. If capture fails, inspect the marker and any partial
record before retrying. Do not silently replace a record whose evidence is
already being prepared.

Collect `baseline.json` and draft `release-notes.md` in this version's directory.
Both must describe the pinned SHA and image digests. The baseline must contain
the SHA in `expected_commit` (or `sha`). If production changes before baseline
collection finishes, stop and reconcile the pod/image identities; do not label
measurements from the new deployment as evidence for the old one.

Include these details in the notes:

- User-visible changes, fixed defects, and breaking changes, linked to PRs.
- Exact commit, successful CI run, and successful GitHub deployment links.
- All six deployed image digests and any changes outside the image bundle.
- Baseline measurements, their timestamp, and the planned 24-hour comparison.
- Known limitations, rollback target, and operational follow-up.

## Publish the Git release

After reviewing the evidence, use only the pinned record. Do not select a new
SHA from the live `deployed.json`. A later deployment can supersede this one
without changing the release being recorded.

```sh
set -eu
REPO=kwehden/HousePanel
VERSION=${VERSION:-v0.1.0}
RELEASE_DIR="build/releases/$VERSION"
RECORD="$RELEASE_DIR/deployment.json"
SHA=$(jq -er .sha "$RECORD")
RUN=$(jq -er .run_id "$RECORD")
DEPLOYMENT=$(jq -er .deployment_id "$RECORD")

test "$(jq -r .status_reported "$RECORD")" = true
test -s "$RELEASE_DIR/release-notes.md"
test "$(jq -er '.expected_commit // .sha' "$RELEASE_DIR/baseline.json")" = "$SHA"
test "$(gh run view "$RUN" --repo "$REPO" --json headSha --jq .headSha)" = "$SHA"
test "$(gh run view "$RUN" --repo "$REPO" --json conclusion --jq .conclusion)" = success
test "$(gh api "repos/$REPO/deployments/$DEPLOYMENT" --jq .sha)" = "$SHA"
# The API returns newest-first pages. Preserve that order across all pages.
STATUSES=$(gh api --paginate "repos/$REPO/deployments/$DEPLOYMENT/statuses?per_page=100")
printf '%s\n' "$STATUSES" | jq -se '
  add | (.[0].state == "success" or .[0].state == "inactive")
        and any(.[]; .state == "success")' > /dev/null

git fetch origin main --tags
git merge-base --is-ancestor "$SHA" origin/main
git tag -a "$VERSION" "$SHA" -m "HousePanel $VERSION; verified deployment $DEPLOYMENT"
git push origin "refs/tags/$VERSION"
gh release create "$VERSION" --repo "$REPO" --verify-tag \
  --title "HousePanel $VERSION" --notes-file "$RELEASE_DIR/release-notes.md"
gh release view "$VERSION" --repo "$REPO"
```

An `inactive` deployment is eligible only with a successful status in its
history. A current failure, error, or unfinished deployment blocks publication.
GitHub retains previous statuses for 90 days; missing historical success must
be investigated, not bypassed. See the [deployment status API](https://docs.github.com/en/rest/deployments/statuses).

Attach a sanitized machine-readable baseline and image manifest as GitHub
release assets with `gh release upload`. Never attach credentials, private
calendar content, raw configuration, or unredacted logs. Download and preserve
the tested `housepanel-release` bundle before its 14-day artifact expiry if
long-term offline recovery is needed. Do not claim that bundle is permanent.

If publication fails after the tag push, retry GitHub release creation using
`--verify-tag`; do not create or move the tag again. If a newer main commit
deploys meanwhile, this release still records the original verified SHA.

## After 24 hours

Compare the same processes against the saved baseline. Report absolute MiB
growth, percent growth, and MiB/hour for each service. Use Prometheus history
to separate startup steps from continuing drift and report RSS and working set
separately. Check threads, file descriptors, queues, delivery failures, and alerts.

A changed pod UID, container ID, or restart count invalidates a continuous
24-hour comparison. Report the interrupted interval and take a new baseline.
RSS growth alone does not prove retained live allocations. Avoid forced GC,
allocator trimming, and production tracing during the observation window.

## Failure and rollback

The agent restores previous image references if rollout or delivery checks
fail, and writes `failed.json`. Inspect the journal and confirm rollback health
before retrying. Never remove that marker just to make a failure disappear.

For a defect found after successful deployment, prepare a reviewed revert or
fix PR. Merging it follows the same tested main deployment path. Publish a new
version describing the recovery; preserve the failed release's tag and notes.
Emergency manual intervention requires explicit user approval and a recorded
SHA/digest, followed by reconciliation with Git and a fresh memory baseline.
