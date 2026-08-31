# AutoShorts Engine — Windows Task Scheduler Installer
# Automatically generates and uploads Shorts to YouTube 2x daily without manual effort.

$batPath = "c:\Users\786mu\OneDrive\Attachments\Desktop\AutoShorts-Engine\auto_upload.bat"

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""

# Run twice daily: 10:00 AM and 06:00 PM
$trigger1 = New-ScheduledTaskTrigger -Daily -At "10:00AM"
$trigger2 = New-ScheduledTaskTrigger -Daily -At "06:00PM"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "AutoShorts-Daily-Upload" `
    -Action $action `
    -Trigger @($trigger1, $trigger2) `
    -Settings $settings `
    -Force

Write-Host "SUCCESS: AutoShorts automatic upload task registered!"
Write-Host "Schedule: Twice daily at 10:00 AM and 06:00 PM."
