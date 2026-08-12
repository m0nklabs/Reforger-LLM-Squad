# Restart bridge in an OPEN interactive console window (user can watch logs)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# Start bridge in a NEW open console window (visible, not minimized)
$workdir = 'Q:\GAMES\Reforger-LLM-Squad\python_bridge'
$py = Join-Path $workdir 'venv\Scripts\python.exe'
Start-Process -FilePath 'cmd.exe' -ArgumentList "/k cd /d $workdir && $py main.py" -WorkingDirectory $workdir

Start-Sleep -Seconds 6
Write-Host "Bridge process started in open console window."
