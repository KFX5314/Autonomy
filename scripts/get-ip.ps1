# scripts/get-ip.ps1
Write-Host "Active IPv4 addresses:`n"

Get-NetIPAddress -AddressFamily IPv4 `
| Where-Object {
    $_.IPAddress -notlike "169.*" -and
    $_.IPAddress -notlike "127.*"
} `
| Select-Object InterfaceAlias, IPAddress `
| Format-Table -AutoSize