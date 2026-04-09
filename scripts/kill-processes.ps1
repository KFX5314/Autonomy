# Kill anything on port 8000 (backend)
Get-NetTCPConnection -LocalPort 8000 -EA 0 | Where-Object { $_.OwningProcess -ne 0 } | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

# Kill anything on port 8081 (frontend)
Get-NetTCPConnection -LocalPort 8081 -EA 0 | Where-Object { $_.OwningProcess -ne 0 } | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }