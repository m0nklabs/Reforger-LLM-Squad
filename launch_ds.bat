@echo off
cd /d "Q:\SteamLibrary\steamapps\common\Arma Reforger Server"
echo Working dir: %CD%
echo Starting DS with config...
ArmaReforgerServer.exe -config "Q:\SteamLibrary\steamapps\common\Arma Reforger Server\server.json"
