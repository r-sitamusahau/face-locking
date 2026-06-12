@echo off
echo Run this file as Administrator (right-click - Run as administrator)
echo.
netsh advfirewall firewall add rule name="FaceLocking MQTT 1884" dir=in action=allow protocol=TCP localport=1884
if errorlevel 1 (
  echo Failed - right-click this file and choose "Run as administrator"
) else (
  echo Firewall rule added for TCP port 1884
)
pause
