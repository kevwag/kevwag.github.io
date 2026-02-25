@echo off
setlocal enabledelayedexpansion

rem Assuming the script is located inside the "rawData" folder
set "DataPath=..\zipped"
set "FinalDataPath=..\tv"


for %%f in (epg.xml iptv.m3u8 sat.m3u8 sky.m3u8) do (
    set "SourceFile=%%f"
    set "DestinationFile=!FinalDataPath!\%%f.gz"
    set "GzippedFile=!DataPath!\%%f.gz"

    if exist "!SourceFile!" (
        echo Gzipping !SourceFile!...
        "C:\Program Files\7-Zip\7z.exe" a -tgzip "!GzippedFile!" "!SourceFile!" > nul
        
       if exist "!GzippedFile!" (
            echo Moving !GzippedFile! to !DestinationFile!...
            move /y "!GzippedFile!" "!DestinationFile!"
        ) else (
            echo Error gzipping !SourceFile!
        )
    ) else (
        echo !SourceFile! not found.
    )
)

echo Script completed.
pause
exit /b 0
