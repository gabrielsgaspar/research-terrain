#!/usr/bin/env bash
# One-time GCS and Workload Identity setup for research-terrain. Run it
# yourself (not through an agent), from WSL, logged in to gcloud as a project
# owner. Safe to run twice: existing service accounts, pools and providers are
# reused, and adding an IAM binding that already exists changes nothing.
#
#   bash scripts/gcp/setup_gcs.sh PROJECT_ID
#
# What it does, in order:
#   1. enables the APIs;
#   2. hardens gs://research-terrain (uniform access, no public access,
#      versioning) and adds lifecycle rules;
#   3. creates four service accounts (acquire, build, analysis, unblind);
#   4. grants each one access to specific prefixes only (table in data/README.md);
#   5. creates a Workload Identity pool and provider that trust only this
#      repository's GitHub Actions, and lets each GitHub environment act as
#      one service account;
#   6. prints (and, if gh is logged in, sets) the two repository variables.
set -euo pipefail

PROJECT_ID="${1:?usage: bash scripts/gcp/setup_gcs.sh PROJECT_ID}"
BUCKET=research-terrain
REPO=gabrielsgaspar/research-terrain
# A pool used only by this repository: bindings below match on the
# environment name, so a pool shared with another repo would let that repo's
# environment of the same name in.
POOL=github-terrain
PROVIDER=research-terrain
OBJ="projects/_/buckets/${BUCKET}/objects"

step() { printf '\n== %s\n' "$*"; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

gcloud config set project "$PROJECT_ID" >/dev/null
NUM=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
sa_email() { echo "terrain-$1@${PROJECT_ID}.iam.gserviceaccount.com"; }

step "1. Enabling APIs"
gcloud services enable storage.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com

step "2. Hardening gs://${BUCKET}"
gcloud storage buckets update "gs://${BUCKET}" \
  --uniform-bucket-level-access --public-access-prevention --versioning
cat > "$tmp/lifecycle.json" <<'EOF'
{"rule": [
  {"action": {"type": "Delete"}, "condition": {"age": 90, "matchesPrefix": ["data/explore/"]}},
  {"action": {"type": "Delete"}, "condition": {"daysSinceNoncurrentTime": 90}}
]}
EOF
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file="$tmp/lifecycle.json"

step "3. Service accounts"
for sa in acquire build analysis unblind; do
  if gcloud iam service-accounts describe "$(sa_email "$sa")" >/dev/null 2>&1; then
    echo "  terrain-${sa} exists"
  else
    gcloud iam service-accounts create "terrain-${sa}" --display-name="research-terrain ${sa}"
  fi
done
echo "  waiting 20s for new accounts to propagate"
sleep 20

# grant SA ROLE TITLE PREFIX...: ROLE on the bucket, limited by an IAM
# condition to objects under the prefixes, and to listings of those prefixes.
# A listing counts if its prefix starts with "data/raw/" or is exactly
# "data/raw": gcloud lists a folder's top level with the trailing slash
# dropped. Any earlier bindings of the same role for the account are removed
# first, so re-running the script replaces conditions instead of piling them up.
grant() {
  local sa=$1 role=$2 title=$3
  shift 3
  local expr="" p
  local attr='api.getAttribute("storage.googleapis.com/objectListPrefix", "")'
  for p in "$@"; do
    [ -n "$expr" ] && expr+=" || "
    expr+="resource.name.startsWith(\"${OBJ}/${p}\")"
    expr+=" || ${attr}.startsWith(\"${p}\") || ${attr} == \"${p%/}\""
  done
  printf "title: %s\nexpression: '%s'\n" "$title" "$expr" > "$tmp/condition.yaml"
  gcloud storage buckets remove-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:$(sa_email "$sa")" --role="$role" --all >/dev/null 2>&1 || true
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:$(sa_email "$sa")" --role="$role" \
    --condition-from-file="$tmp/condition.yaml" >/dev/null
  echo "  terrain-${sa}: ${role#roles/storage.} on $*"
}

step "4. Prefix-scoped access"
grant acquire  roles/storage.objectViewer  acquire-read   data/raw/
grant acquire  roles/storage.objectCreator acquire-create data/raw/
grant build    roles/storage.objectViewer  build-read     data/raw/ data/derived/
# sealed/outcomes/: confirmation-half outcome rows (decision 0003), create-only;
# terrain-analysis gets nothing there, terrain-unblind reads it through sealed/.
grant build    roles/storage.objectCreator build-create   data/derived/ sealed/outcomes/
grant analysis roles/storage.objectViewer  analysis-read  data/derived/ data/explore/
grant analysis roles/storage.objectAdmin   analysis-write data/explore/
grant unblind  roles/storage.objectViewer  unblind-read   data/derived/ sealed/

step "5. Workload Identity Federation"
if gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1; then
  echo "  pool ${POOL} exists"
else
  gcloud iam workload-identity-pools create "$POOL" --location=global \
    --display-name="GitHub Actions: research-terrain"
fi
if gcloud iam workload-identity-pools providers describe "$PROVIDER" \
    --location=global --workload-identity-pool="$POOL" >/dev/null 2>&1; then
  echo "  provider ${PROVIDER} exists"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --location=global --workload-identity-pool="$POOL" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment" \
    --attribute-condition="assertion.repository == '${REPO}'"
fi
principal="principalSet://iam.googleapis.com/projects/${NUM}/locations/global/workloadIdentityPools/${POOL}/attribute.environment"
for pair in acquire:data-write build:data-write analysis:analysis unblind:unblind; do
  sa=${pair%%:*} env=${pair#*:}
  gcloud iam service-accounts add-iam-policy-binding "$(sa_email "$sa")" \
    --role=roles/iam.workloadIdentityUser --member="${principal}/${env}" >/dev/null
  echo "  environment ${env} -> terrain-${sa}"
done

step "6. Repository variables"
WIF="projects/${NUM}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
echo "  GCP_PROJECT_ID=${PROJECT_ID}"
echo "  GCP_WIF_PROVIDER=${WIF}"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh variable set GCP_PROJECT_ID -R "$REPO" --body "$PROJECT_ID"
  gh variable set GCP_WIF_PROVIDER -R "$REPO" --body "$WIF"
  echo "  set both on ${REPO}"
else
  echo "  gh not logged in: add both under Settings -> Secrets and variables -> Actions -> Variables"
fi

printf '\nDone. Next: run the "GCS smoke test" workflow from the Actions tab.\n'
