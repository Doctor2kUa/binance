# ═══ REGISTRY SECRET ═══
# Создать GHCR token (GitHub → Settings → Tokens → Fine-grained)
# с правами: read:packages (scopes: read:packages)
# Затем создать секрет:
#
# kubectl create secret docker-registry ghcr-watchlist-agent \
#   --docker-server=ghcr.io \
#   --docker-username=YOUR_GITHUB_USERNAME \
#   --docker-password=YOUR_GITHUB_TOKEN \
#   --namespace=function

# ═══ AGENT SECRETS (Telegram + OpenRouter) ═══
# Добавь потом:
#
# kubectl create secret generic binance-watchlist-secrets \
#   --from-literal=OPENROUTER_API_KEY=*** \
#   --from-literal=BOT_TOKEN=*** \
#   --from-literal=CHAT_ID=XXXXXXXX \
#   --namespace=function

# ═══ ИНСТРУКЦИЯ ═══
# 1. GHCR: в настройках GitHub repo binance → Secrets → Actions →
#    используй GITHUB_TOKEN (уже есть) — workflow сам пушит
#
# 2. K8s image pull secret:
#    kubectl create secret docker-registry ghcr-watchlist-agent \
#      --docker-server=ghcr.io \
#      --docker-username=Doctor2kUa \
#      --docker-password=<GITHUB_TOKEN_WITH_READ_PACKAGES> \
#      --namespace=function
#
# 3. Agent runtime secrets:
#    kubectl create secret generic binance-watchlist-secrets \
#      --from-literal=OPENROUTER_API_KEY=sk-or-xxx \
#      --from-literal=BOT_TOKEN=xxx \
#      --from-literal=CHAT_ID=-100... \
#      --namespace=function
