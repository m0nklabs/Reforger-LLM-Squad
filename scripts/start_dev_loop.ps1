# start_dev_loop.ps1 — start the night dev loop in an OPEN console window
$workdir = 'Q:\GAMES\Reforger-LLM-Squad'
Start-Process -FilePath 'cmd.exe' -ArgumentList "/k cd /d $workdir && powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev_loop.ps1" -WorkingDirectory $workdir
Write-Host "Dev loop started in open console window."
