# demo.ps1 — team undefeated: one-command demo of all three roles (Windows PowerShell).
#   .\demo.ps1            # checks + duels + prosecutor score, then opens the battle replay
#   .\demo.ps1 -NoUI      # same, without starting the replay server
param([switch]$NoUI, [string]$Bot = "adversary", [int]$Seed = 1)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$py = ".\.venv\Scripts\python.exe"
Set-Location $PSScriptRoot

function Step($title) { Write-Host "`n=== $title ===" -ForegroundColor Cyan }

Step "1. Readiness (make doctor)"
& $py -m kit.gate_no_key
& $py -c "from kit.referee.rubric import CLASSES; print(f'referee: {len(CLASSES)} classes')"
& $py validate_deck.py deck/deck.json deck/lineup.json --world kit/world/df8c55dabb35/ | Select-Object -Last 1

Step "2. DEFEND — gateway decisions on a hand-made attack"
& $py demo_cases.py gateway

Step "3. Answer side — guardrails on a poisoned draft"
& $py demo_cases.py answer

Step "4. PROSECUTE — kit fixtures (40) + team selfcheck (13)"
& $py -m eval.selfcheck | Select-String "===|filed"

Step "5. Duels vs the three bots (all roles, seed $Seed)"
foreach ($b in "rookie", "operator", "adversary") {
    & $py spar.py --bot $b --as all --seed $Seed | Select-String "RESULT"
}

Step "6. Full duel report vs $Bot (look at MISSED, not HP)"
& $py spar.py --bot $Bot --as all --seed $Seed --ui

if (-not $NoUI) {
    Step "7. Battle replay (Ctrl+C to stop)"
    & $py -m kit.arena_ui.build_ui | Out-Null
    & $py -m kit.arena_ui.serve --run "spar-$Bot-$Seed"
}
