#!/bin/sh
# Container entrypoint dispatcher for the S1-Episode funding trader.
#
#   trade      (default)  -> python main.py  (paper or live per config.yaml runtime.mode)
#   preflight             -> read-only go/no-go checks (account reads + gateway probe)
#   roundtrip [SYMBOL]    -> GATED tiny real order round-trip (needs MEXC_ALLOW_LIVE_ORDERS=1)
#   rehearsal [SYM] [N]   -> GATED full execution dress rehearsal
#   test                  -> run the unit + integration test suite
#   <anything else>       -> exec it verbatim (e.g. `sh` for a shell)
set -e

cmd="${1:-trade}"
case "$cmd" in
  trade)
    exec python main.py
    ;;
  preflight)
    echo "=== READ-ONLY characterization (account, universe, fees) ==="
    python -m experiments.characterize
    echo
    echo "=== Gateway probe (which MEXC host accepts order/submit) ==="
    python -m experiments.domain_probe
    echo
    echo "GO/NO-GO: proceed only if equity is funded AND contract.mexc.co shows 'trading path OPEN' above."
    ;;
  roundtrip)
    shift
    exec python -m experiments.order_roundtrip "$@"
    ;;
  rehearsal)
    shift
    exec python -m experiments.execution_dress_rehearsal "$@"
    ;;
  test)
    exec python -m pytest tests/unit tests/integration -q
    ;;
  *)
    exec "$@"
    ;;
esac
