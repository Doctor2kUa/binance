#!/bin/bash
# deploy.sh — Deploy all Binance CronJobs
# Usage: bash deploy.sh [--test]
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="function"
TEST_MODE=false
for arg in "$@"; do case $arg in --test) TEST_MODE=true ;; esac; done

export KUBECONFIG="${KUBECONFIG:-$HOME/Downloads/core-1-4-kubeconfig.yaml}"

echo "═══════════════════════════════════════════"
echo "  Deploy Binance CronJobs"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════"
echo ""

echo "[1/4] Checking secret..."
kubectl get secret binance-telegram -n "$NAMESPACE" &>/dev/null || { echo "  Secret not found!"; exit 1; }
echo "  OK"
echo ""

echo "[2/4] Applying ConfigMaps..."
kubectl apply -f "$SCRIPT_DIR/config.yaml" -n "$NAMESPACE" 2>&1 | tail -1
kubectl apply -f "$SCRIPT_DIR/scripts.yaml" -n "$NAMESPACE" 2>&1 | tail -1
echo "  OK"
echo ""

echo "[3/4] Applying CronJobs..."
kubectl apply -f "$SCRIPT_DIR/cronjob-report.yaml" -n "$NAMESPACE" 2>&1 | tail -1
kubectl apply -f "$SCRIPT_DIR/cronjob-monitor.yaml" -n "$NAMESPACE" 2>&1 | tail -1
echo "  OK"
echo ""

echo "[4/4] Status..."
sleep 2
kubectl get cronjobs -n "$NAMESPACE"
echo ""

if [ "$TEST_MODE" = true ]; then
  echo "Testing report..."
  J="test-$(date +%s)"
  kubectl create job -n "$NAMESPACE" --from=cronjob/binance-report "$J" 2>&1 | tail -1
  sleep 25
  kubectl logs -n "$NAMESPACE" "job/$J" 2>&1 | head -30
  kubectl delete job -n "$NAMESPACE" "$J" 2>/dev/null
  echo "  OK"
  echo ""

  echo "Testing monitor..."
  J="mon-$(date +%s)"
  kubectl create job -n "$NAMESPACE" --from=cronjob/binance-monitor "$J" 2>&1 | tail -1
  sleep 25
  kubectl logs -n "$NAMESPACE" "job/$J" 2>&1 | head -20
  kubectl delete job -n "$NAMESPACE" "$J" 2>/dev/null
  echo "  OK"
  echo ""
fi

echo "═══════════════════════════════════════════"
echo "  Done!"
echo ""
echo "  Update positions/watchlist:"
echo "    1. Edit k8s/config.yaml"
echo "    2. kubectl apply -f k8s/config.yaml"
echo "═══════════════════════════════════════════"
