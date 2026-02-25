@echo off
cls
rem echo TEMPEST EPG GRABBER
rem echo.
rem echo Starting EPG Grab for ALL Channels...
rem echo.
rem php C:\inetpub\wwwroot\tempest.php engine=Generate tempconfig=EPG.config.xml
echo.
echo Copying xmltv file epg.xml to the web server...
if exist "C:\inetpub\wwwroot\tv\epg.xml" (
    echo deleting C:\inetpub\wwwroot\tv\epg.xml
	del C:\inetpub\wwwroot\tv\epg.xml
) else (
    echo Error deleting C:\inetpub\wwwroot\tv\epg.xml (file not found)
)
if exist "C:\inetpub\wwwroot\tempest_config\epg\epg.xml" (
    echo copying C:\inetpub\wwwroot\tempest_config\epg\epg.xml >> C:\inetpub\wwwroot\tv
	xcopy /f /v /y C:\inetpub\wwwroot\tempest_config\epg\epg.xml C:\inetpub\wwwroot\tv
) else (
    echo Error copying C:\inetpub\wwwroot\tempest_config\epg\epg.xml (file not found)
)
echo.

rem GZIP M3U8 & XML FILES
setlocal enabledelayedexpansion
md temp
set "TempPath=C:\inetpub\wwwroot\tv\temp"
set "wwwPath=C:\inetpub\wwwroot\tv"
set "GithubPath=C:\Users\Kevin\GitHub\kevwag.github.io\tv"

for %%f in (epg.xml iptv.m3u8 sat.m3u8 sky.m3u8) do (
    set "SourceFile=%%f"
    set "DestinationFile=!wwwPath!\%%f.gz"
    set "GzippedFile=!TempPath!\%%f.gz"

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
rd temp
echo.
echo Gzipping complete...
echo.
rem UPDATE FILES IN GIT FOLODER
echo.
echo Copy (replace) files from local webserver to git staging folder...
echo.
for %%g in (epg.xml epg.xml.gz iptv.m3u8.gz sat.m3u8.gz sky.m3u8.gz) do (
    set "TargetFile=%%g"

    if exist "!GithubPath!\!TargetFile!" (
        echo Deleting !GithubPath!\!TargetFile!...
        del "!GithubPath!\!TargetFile!"
        
        if exist "!wwwPath!\!TargetFile!" (
            echo Copying !wwwPath!\!TargetFile! to !GithubPath!...
            xcopy /f /v /y "!wwwPath!\!TargetFile!" "!GithubPath!"
        ) else (
            echo Error copying !TargetFile!
        )
    ) else (
        echo !TargetFile! not found.
    )
)

rem COMMIT FILES IN GIT FOLDER AND PUSH TO GITHUB REMOTE (KEVWAG.GITHUB.IO)
echo.
echo Uploading via git...
echo.
cd\
cd Users\Kevin\GitHub\kevwag.github.io
git add *.*
git commit -m "EPG Update"
git push origin master
echo.
echo.
echo Updating NextPVR EPG...
echo.
"C:\Program Files\NextPVR\NScriptHelper.exe" -pin:2018 -updateepg
echo.
pause
exit /b 0
