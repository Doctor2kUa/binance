# ═══ GHCR Pull Secret для binance-watchlist-agent ═══
# Создай Fine-grained PAT на GitHub:
#   Settings → Developer settings → Personal access tokens → Fine-grained → New
#   Repository: Doctor2kUa/binance
#   Permissions: Packages (Read) + Contents (Read) + Metadata (Read)
#
# Затем:
#   export GHCR_PAT=<твой_токен>
#   kubectl create secret docker-registry ghcr-watchlist-agent \
#     --docker-server=ghcr.io \
#     --docker-username=Doctor2kUa \
#     --docker-password=$GHCR_PAT \
#     --namespace=function
#
# Проверка:
#   kubectl get secret ghcr-watchlist-agent -n function
#   kubectl apply -f agent/k8s/serviceaccount.yaml
#   kubectl apply -f agent/k8s/knative-service.yaml
