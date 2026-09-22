param([ValidateSet('up', 'down', 'reset')][string]$Command = 'up')
$ErrorActionPreference = 'Stop'
if ($Command -eq 'up') {
    docker compose up --build --wait
    Write-Host 'Dashboard: http://127.0.0.1:8080'
} elseif ($Command -eq 'reset') {
    docker compose down --volumes
} else {
    docker compose down
}
