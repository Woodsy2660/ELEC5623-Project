#!/usr/bin/env bash
# Foundry deployment for Consulting-Agent-System, via Azure CLI.
#
# Three phases. Run them in order and read the output of each before moving on.
#
#   ./foundry_deploy.sh discover
#   ./foundry_deploy.sh deploy-chat  <model-name> <model-version> [capacity]
#   ./foundry_deploy.sh deploy-embed <model-name> <model-version> [capacity]
#   ./foundry_deploy.sh grant <email> [<email> ...]
#   ./foundry_deploy.sh verify
#
# Nothing here is destructive except `grant`, which adds role assignments.
# Everything the script prints is worth keeping for the report.

set -euo pipefail

RESOURCE="${CIA_RESOURCE:-Consulting-Agent-System}"
CHAT_DEPLOYMENT="${CIA_CHAT_DEPLOYMENT:-cia-chat}"
EMBED_DEPLOYMENT="${CIA_EMBED_DEPLOYMENT:-cia-embed}"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

require_az() {
  command -v az >/dev/null 2>&1 || die "Azure CLI not installed. See https://learn.microsoft.com/cli/azure/install-azure-cli"
  az account show >/dev/null 2>&1 || die "not signed in — run: az login"
}

# Resolve the resource group once; every later command needs it.
find_rg() {
  local rg
  rg=$(az cognitiveservices account list \
        --query "[?name=='${RESOURCE}'].resourceGroup | [0]" -o tsv 2>/dev/null || true)
  [ -n "$rg" ] && [ "$rg" != "None" ] || die "resource '${RESOURCE}' not found in this subscription.
Check you are on the right subscription:  az account show -o table
List what is visible:                     az cognitiveservices account list -o table
Switch if needed:                         az account set --subscription <id>"
  printf '%s' "$rg"
}

# ---------------------------------------------------------------------------
cmd_discover() {
  require_az
  local rg; rg=$(find_rg)

  bold "Subscription"
  az account show --query "{name:name, id:id, user:user.name}" -o table

  bold "Resource"
  az cognitiveservices account show -n "$RESOURCE" -g "$rg" \
    --query "{name:name, kind:kind, sku:sku.name, location:location, provisioning:properties.provisioningState}" \
    -o table

  bold "Endpoint(s) — the one your .env needs"
  # Classic OpenAI resources expose a single endpoint; AIServices/Foundry
  # resources expose several, keyed by API surface. Print whatever exists.
  az cognitiveservices account show -n "$RESOURCE" -g "$rg" \
    --query "properties.endpoint" -o tsv 2>/dev/null || true
  az cognitiveservices account show -n "$RESOURCE" -g "$rg" \
    --query "properties.endpoints" -o json 2>/dev/null || true

  bold "Existing deployments"
  az cognitiveservices account deployment list -n "$RESOURCE" -g "$rg" \
    --query "[].{name:name, model:properties.model.name, version:properties.model.version, sku:sku.name, capacity:sku.capacity, upgrade:properties.versionUpgradeOption}" \
    -o table 2>/dev/null || echo "(none yet)"

  bold "Deployable chat models"
  echo "Look for one whose capabilities include structured / JSON-schema output."
  # list-models returns a flat object (name, version, capabilities, skus),
  # not a nested model.* record. The deployment APIs are the ones that nest.
  az cognitiveservices account list-models -n "$RESOURCE" -g "$rg" \
    --query "[?capabilities.chatCompletion != null].{model:name, version:version, skus:join(', ', skus[].name), status:lifecycleStatus, schema:capabilities.jsonSchemaResponse}" \
    -o table 2>/dev/null || echo "(list-models returned nothing — check the region)"

  bold "Deployable embedding models"
  az cognitiveservices account list-models -n "$RESOURCE" -g "$rg" \
    --query "[?capabilities.embeddings != null].{model:name, version:version, skus:join(', ', skus[].name), status:lifecycleStatus}" \
    -o table 2>/dev/null || echo "(none listed)"

  bold "Capabilities detail (inspect your candidate model here)"
  echo "The capability key names vary by model family, so read rather than filter:"
  echo "  az cognitiveservices account list-models -n ${RESOURCE} -g ${rg} \\"
  echo "    --query \"[?name=='<MODEL>'].capabilities\" -o json"

  local loc
  loc=$(az cognitiveservices account show -n "$RESOURCE" -g "$rg" --query location -o tsv)
  bold "Quota in ${loc} — 'limit' minus 'currentValue' is what you can still deploy"
  az cognitiveservices usage list -l "$loc" \
    --query "[?contains(name.value, 'OpenAI')].{quota:name.localizedValue, used:currentValue, limit:limit}" \
    -o table 2>/dev/null || echo "(usage list unavailable)"

  bold "Next"
  echo "  ./foundry_deploy.sh deploy-chat  <model> <version> [capacity]"
  echo "  ./foundry_deploy.sh deploy-embed <model> <version> [capacity]"
  echo
  echo "Capacity is in thousands of tokens per minute. Your workload is ~24k"
  echo "tokens per meeting, and a single extraction call is ~8-10k. Below about"
  echo "30 you will be rate-limited and the harness must serialise with backoff."
}

# ---------------------------------------------------------------------------
# Shared deployment routine. Tries GlobalStandard, falls back to Standard.
deploy() {
  local dep="$1" model="$2" version="$3" capacity="${4:-50}"
  local rg; rg=$(find_rg)

  if az cognitiveservices account deployment show \
       -n "$RESOURCE" -g "$rg" --deployment-name "$dep" >/dev/null 2>&1; then
    die "deployment '${dep}' already exists.
Never repoint an existing deployment at a different model — run logs stop being
unambiguous. Create '${dep}-v2' instead, or delete this one first:
  az cognitiveservices account deployment delete -n ${RESOURCE} -g ${rg} --deployment-name ${dep}"
  fi

  # Azure CLI 2.91's deployment create does not accept --version-upgrade-option.
  # The property is versionUpgradeOption=NoAutoUpgrade on the deployment resource.
  # If this flag is rejected, create the deployment with `az rest` PUT and that
  # property set, using control-plane api-version 2025-06-01. Do not omit the pin.
  for sku in GlobalStandard Standard; do
    bold "Deploying ${dep}: ${model} ${version}, sku=${sku}, capacity=${capacity}"
    if az cognitiveservices account deployment create \
         -n "$RESOURCE" -g "$rg" \
         --deployment-name "$dep" \
         --model-name "$model" \
         --model-version "$version" \
         --model-format OpenAI \
         --sku-name "$sku" \
         --sku-capacity "$capacity" \
         --version-upgrade-option NoAutoUpgrade \
         -o none 2>/tmp/cia_deploy_err; then
      printf '\033[32mdeployed\033[0m %s (%s)\n' "$dep" "$sku"
      az cognitiveservices account deployment show \
        -n "$RESOURCE" -g "$rg" --deployment-name "$dep" \
        --query "{name:name, model:properties.model.name, version:properties.model.version, sku:sku.name, capacity:sku.capacity, upgrade:properties.versionUpgradeOption, state:properties.provisioningState}" \
        -o table
      return 0
    fi
    echo "  ${sku} failed:"
    sed 's/^/    /' /tmp/cia_deploy_err
  done

  die "both SKUs failed. Usually quota — lower the capacity, or check:
  az cognitiveservices usage list -l \$(az cognitiveservices account show -n ${RESOURCE} -g ${rg} --query location -o tsv) -o table"
}

cmd_deploy_chat() {
  require_az
  [ $# -ge 2 ] || die "usage: $0 deploy-chat <model-name> <model-version> [capacity]"
  deploy "$CHAT_DEPLOYMENT" "$@"
  bold "Verify structured output before building on this"
  echo "  python scripts/smoke_test_foundry.py"
  echo "Test 2 is the one that matters: if an out-of-enum value ever comes back,"
  echo "you have JSON mode rather than schema enforcement, and FR07's guarantee"
  echo "is validate-and-retry instead of structural."
}

cmd_deploy_embed() {
  require_az
  [ $# -ge 2 ] || die "usage: $0 deploy-embed <model-name> <model-version> [capacity]"
  deploy "$EMBED_DEPLOYMENT" "$@"
  bold "Record the embedding dimension"
  echo "The smoke test prints it. It goes in EMBED_DIM and in"
  echo "requirement_versions.embedding_dim. If it differs from what is already"
  echo "stored, every existing vector is orphaned and must be rebuilt."
}

# ---------------------------------------------------------------------------
cmd_grant() {
  require_az
  [ $# -ge 1 ] || die "usage: $0 grant <email> [<email> ...]"
  local rg scope; rg=$(find_rg)
  scope=$(az cognitiveservices account show -n "$RESOURCE" -g "$rg" --query id -o tsv)

  for who in "$@"; do
    bold "Granting inference access to ${who}"
    # "Cognitive Services OpenAI User" permits inference but not management.
    # On some Foundry resource kinds the equivalent is "Azure AI Developer".
    if ! az role assignment create \
           --assignee "$who" \
           --role "Cognitive Services OpenAI User" \
           --scope "$scope" -o none 2>/tmp/cia_role_err; then
      echo "  'Cognitive Services OpenAI User' failed, trying 'Azure AI Developer'"
      sed 's/^/    /' /tmp/cia_role_err
      az role assignment create \
        --assignee "$who" \
        --role "Azure AI Developer" \
        --scope "$scope" -o none \
        || die "both roles failed for ${who} — you may lack permission to assign roles"
    fi
    printf '\033[32mgranted\033[0m %s\n' "$who"
  done

  bold "Current assignments on this resource"
  az role assignment list --scope "$scope" \
    --query "[].{who:principalName, role:roleDefinitionName}" -o table

  echo
  echo "Role propagation takes a few minutes. Anyone who gets a 401 straight"
  echo "after should run 'az logout && az login' — a token issued before the"
  echo "assignment does not carry the new role."
}

# ---------------------------------------------------------------------------
cmd_verify() {
  require_az
  local rg; rg=$(find_rg)

  bold "Deployments"
  az cognitiveservices account deployment list -n "$RESOURCE" -g "$rg" \
    --query "[].{name:name, model:properties.model.name, version:properties.model.version, sku:sku.name, capacity:sku.capacity, upgrade:properties.versionUpgradeOption, state:properties.provisioningState}" \
    -o table

  bold "Version pinning check"
  local bad
  bad=$(az cognitiveservices account deployment list -n "$RESOURCE" -g "$rg" \
          --query "[?properties.versionUpgradeOption != 'NoAutoUpgrade'].name" -o tsv)
  if [ -n "$bad" ]; then
    printf '\033[31mNOT PINNED:\033[0m %s\n' "$bad"
    echo "Azure can update these mid-semester. Prompts you froze would then be"
    echo "scored against a different model than you developed against, and the"
    echo "holdout results are not comparable to anything. Fix with:"
    echo "  az cognitiveservices account deployment create -n ${RESOURCE} -g ${rg} \\"
    echo "    --deployment-name <name> --model-name <m> --model-version <v> \\"
    echo "    --model-format OpenAI --version-upgrade-option NoAutoUpgrade ..."
  else
    printf '\033[32mall deployments pinned\033[0m\n'
  fi

  bold "Endpoint for .env"
  local ep
  ep=$(az cognitiveservices account show -n "$RESOURCE" -g "$rg" \
        --query "properties.endpoint" -o tsv 2>/dev/null || true)
  [ -n "$ep" ] && [ "$ep" != "None" ] || \
    ep=$(az cognitiveservices account show -n "$RESOURCE" -g "$rg" \
          --query "properties.endpoints.\"OpenAI Language Model Instance API\"" -o tsv 2>/dev/null || true)

  cat <<EOF

CIA_FOUNDRY_ENDPOINT=${ep}
CIA_API_VERSION=<see below>
CIA_CHAT_DEPLOYMENT=${CHAT_DEPLOYMENT}
CIA_EMBED_DEPLOYMENT=${EMBED_DEPLOYMENT}

The API version is the one thing the CLI cannot tell you — it is a client-side
choice, not a property of the deployment. Take it from the current Azure OpenAI
REST documentation, or from the sample code on the deployment page in
ai.azure.com. Pin an explicit version; structured-output behaviour has changed
between versions, so "latest" is not reproducible.

Then:
  az login
  python scripts/smoke_test_foundry.py
EOF
}

# ---------------------------------------------------------------------------
case "${1:-}" in
  discover)      shift; cmd_discover "$@" ;;
  deploy-chat)   shift; cmd_deploy_chat "$@" ;;
  deploy-embed)  shift; cmd_deploy_embed "$@" ;;
  grant)         shift; cmd_grant "$@" ;;
  verify)        shift; cmd_verify "$@" ;;
  *)
    sed -n '2,16p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
    exit 1 ;;
esac
