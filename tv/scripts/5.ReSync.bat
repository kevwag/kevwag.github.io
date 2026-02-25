@ECHO OFF
cls
rem REPLACE FILES IN GIT FOLDER WITH FILES PULLED FROM GITHUB REMOTE (KEVWAG.GITHUB.IO)
echo.
echo DOWNLOADING FILES FROM GITHUB...
echo.
cd\
cd Users\Kevin\GitHub\kevwag.github.io
git puLL origin master
echo.
echo FINISHED DOWNLOADING FILES.
echo.
pause
rem SET VARIABLES
setlocal enabledelayedexpansion
cd\
cd inetpub\wwwroot\tv
md temp
set "TempPath=C:\inetpub\wwwroot\tv\temp"
set "wwwPath=C:\inetpub\wwwroot\tv"
set "GithubPath=C:\Users\Kevin\GitHub\kevwag.github.io\tv"
rem UPDATE FILES IN GIT FOLODER
echo.
echo COPYING FILES FROM GIT STAGING FOLDER...
echo.
for %%g in (iptv.m3u8.gz sat.m3u8.gz sky.m3u8.gz epg.xml.gz) do (
    set "TargetFile=%%g"
    if exist "!wwwPath!\!TargetFile!" (
        echo Deleting !wwwPath!\!TargetFile!...
        del /q "!wwwPath!\!TargetFile!"        
        if exist "!GithubPath!\!TargetFile!" (
            echo Copying !GithubPath!\!TargetFile! to !wwwPath!...
            xcopy /f /v /y "!GithubPath!\!TargetFile!" "!wwwPath!"
        ) else (
            echo Error copying !TargetFile!
        )
    ) else (
        echo !TargetFile! not found.
    )
)
echo.
echo GZ FILES COPIED FROM GIT STAGING FOLDER.
echo.
pause
cls
rem UN-GZIP THE M3U8 & XML FILES ON LOCAL WEBSERVER
echo UNZIPPING GZ FILES ON LOCAL WEBSERVER...
echo.
for %%f in (iptv.m3u8.gz sat.m3u8.gz sky.m3u8.gz epg.xml.gz) do (
    set "SourceFile=%%f"
    if exist "!SourceFile!" (
        echo GUnzipping !SourceFile!...
        "C:\Program Files\7-Zip\7z.exe" e -y -tgzip "!SourceFile!"
    ) else ( 
        echo !SourceFile! not found.
    )
)
echo.
echo UNZIP FILES COMPLETE.
echo.
pause
cls
echo.
echo UPDATING NEXTPVR EPG...
echo.
"C:\Program Files\NextPVR\NScriptHelper.exe" -pin:2018 -updateepg
echo.
echo NEXTPVR EPG UPDATE COMPLETE
echo.
pause
cls
echo.
echo GITHUB ==> LOCAL WEBSERVER RE-SYNC COMPLETE
echo.
pause
exit /b 0
